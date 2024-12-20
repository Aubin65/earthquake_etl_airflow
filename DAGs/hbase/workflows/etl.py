"""
Ce fichier est utilisé pour mettre en place l'ETL grâce à Apache Airflow
"""

# Import des librairies nécessaires
from airflow.decorators import dag, task  # noqa
from airflow.exceptions import AirflowException  # noqa
import pendulum  # noqa
import happybase  # noqa
import requests  # noqa
from datetime import datetime, timezone  # noqa
from geopy.distance import geodesic  # noqa
from hbase.useful_functions.encoding_functions import var_to_bytes, bytes_to_var  # noqa

# DAG de base
default_args = {
    "owner": "airflow",
    "retries": 0,
}


# Définition des fonctions de DAG
@dag(
    schedule="*/1 * * * *",  # Exécution toutes les minutes
    default_args=default_args,
    start_date=pendulum.today("UTC").add(days=-1),
    max_active_runs=1,  # Ici on définit ce paramètre à 1 pour empêcher les doublons d'exécution de ce DAG
    catchup=False,
    tags=["earthquake_dag_hbase"],
)
def earthquake_etl_hbase():
    """DAG global d'import des données des tremblement de terre depuis le fichier csv des données brutes vers la base de données HBase"""

    @task
    def extract(
        host: str = "localhost",
        port: int = 9090,
        table_name: str = "earthquakes",
        request: str = "https://earthquake.usgs.gov/fdsnws/event/1/query?",
        format: str = "geojson",
        starttime: pendulum.datetime = pendulum.now("UTC").add(days=-1).strftime("%Y-%m-%dT%H:%M:%S"),
    ) -> dict:
        """Fonction d'extraction de la donnée

        Parameters
        ----------
        host : str, optional
            hote de la bdd HBase, by default "localhost"
        port : int, optional
            port utilisé par la bdd HBase, by default 9090
        table_name : str, optional
            table utilisée pour stocker les données, by default "earthquakes"
        request : _type_, optional
            corps de base de la requête API, by default "https://earthquake.usgs.gov/fdsnws/event/1/query?"
        format : str, optional
            format de la réponse, by default "geojson"
        starttime : _type_, optional
            date de début par défaut, by default pendulum.now("UTC").add(days=-1).strftime("%Y-%m-%dT%H:%M:%S")

        Returns
        -------
        dict
            données brutes

        Raises
        ------
        AirflowException
            exception de stop du DAG si il n'y a pas de nouvel enregistrement
        """

        # -------------------------------------------------------------------------------------------------------------------------------------------#
        # Connexion à la base de données HBase
        connection = happybase.Connection(host=host, port=port)

        # Vérification de la connexion
        connection.open()

        # Connexion à la table :
        table = connection.table(table_name)

        # -------------------------------------------------------------------------------------------------------------------------------------------#
        # Récupération de la date la plus récente

        # Si la table existe et n'est pas vide, on assigne la dernière date à la variable starttime
        if var_to_bytes(table_name) in connection.tables():
            if sum(1 for _ in table.scan()) > 0:

                # Itération sur la table
                for _, data in table.scan(limit=1):

                    # Récupération de la date (pas de prise en compte des doublons qui interviennent juste dans la row key)
                    starttime = bytes_to_var(data[b"general:date"])

        # -------------------------------------------------------------------------------------------------------------------------------------------#
        # Requête API
        final_api_request = f"{request}format={format}&starttime={starttime}"

        raw_data = requests.get(final_api_request, timeout=15).json()

        # -------------------------------------------------------------------------------------------------------------------------------------------#
        # Fermeture du client HBase
        connection.close()

        # -------------------------------------------------------------------------------------------------------------------------------------------#
        # Vérification de l'existence de features

        if len(raw_data["features"]) > 0:
            return raw_data
        else:
            raise AirflowException("pas de nouveaux features, arrêt du DAG.")

    @task
    def transform(raw_data: dict, own_position: tuple = (43.46602, -0.75166)) -> list[dict]:
        """Tâche de transformation du DataFrame brut

        Parameters
        ----------
        raw_data : dict
            dictionnaire issu de la requête get
        own_position : tuple, optional
            position à laquelle on se trouve, by default (43.46602, -0.75166) (position d'Octime)

        Returns
        -------
        list
            liste des éléments à stocker au bon format
        """

        # Initialisation de la liste contenant les séismes
        earthquakes_list = []

        # Initialisation de la liste des clés en cas de doublons
        keys = []

        for feature in raw_data["features"]:

            # Ajout des coordonnées du séisme dans un tuple pour calculer la distance
            point = (feature["geometry"]["coordinates"][1], feature["geometry"]["coordinates"][0])

            # Initialisation de la key row pour insérer dans HBase
            key = str((1 / (feature["properties"]["time"] / 1000)) * 1e12).split(".")[-1]

            # Gestion des doublons de row key
            i = 1
            while key in keys:
                key += " - " + str(i)
                i += 1

            keys.append(key)

            # Création du dictionnaire temporaire
            # On convertit les int et float en byte au format compact
            temp_dict = {
                "stats:magType": feature["properties"]["magType"],
                "stats:mag": feature["properties"]["mag"],
                "general:place": feature["properties"]["place"],
                "general:date": datetime.fromtimestamp(feature["properties"]["time"] / 1000, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "general:type": feature["properties"]["type"],
                "stats:nst": feature["properties"]["nst"],
                "stats:dmin": feature["properties"]["dmin"],
                "stats:sig": feature["properties"]["sig"],
                "coordinates:geometryType": feature["geometry"]["type"],
                "coordinates:longitude": point[1],
                "coordinates:latitude": point[0],
                "coordinates:depth": feature["geometry"]["coordinates"][2],
                "stats:distance_from_us_km": round(geodesic(point, own_position).kilometers, 2),
            }

            print(f"Le dictionnaire est le suivant : {temp_dict}")

            # Ajout à la liste finale
            earthquakes_list.append((key, temp_dict))

        return earthquakes_list

    @task
    def load(
        earthquakes_list: list,
        host: str = "localhost",
        port: int = 9090,
        table: str = "earthquakes",
        batch_size: int = 1000,
        split_batch: bool = False,
    ) -> None:
        """Tâche de chargement des données dans la base de données MongoDB

        Parameters
        ----------
        earthquakes_list : list
            liste de tuples contenant les row keys et les dictionnaires correspondant à chaque enregistrement de tremblement de terre
        """

        # Connexion à la base de données HBase
        connection = happybase.Connection(host=host, port=port)

        # Vérification de la connexion
        connection.open()

        # Connexion à la table :
        if var_to_bytes(table) not in connection.tables():
            print(f"La table '{table}' n'existe pas. Création en cours...")

            # Initialisation des familles
            column_families = {
                "stats": dict(max_versions=1),
                "general": dict(max_versions=1),
                "coordinates": dict(max_versions=1),
            }

            # Créer la table avec les familles de colonnes dynamiques
            connection.create_table("earthquakes", column_families)

            print(f"La table '{table}' a été créée avec succès.")

        # Connexion à la table :
        table = connection.table(table)

        # Condition sur la taille du batch
        if split_batch:

            # Initialisation du batch
            with table.batch(batch_size=batch_size) as batch:

                # Itération sur chaque enregistrement
                for record in earthquakes_list:

                    # Récupération de la row key et de la donnée correspondante
                    key, data = record

                    # Encodage du dictionnaire
                    encoded_data = {var_to_bytes(key): var_to_bytes(elem) for key, elem in data.items()}

                    # Insertion des données
                    batch.put(key, encoded_data)

        else:

            # Initialisation du batch
            with table.batch() as batch:

                # Itération sur chaque enregistrement
                for record in earthquakes_list:

                    # Récupération de la row key et de la donnée correspondante
                    key, data = record

                    # Encodage du dictionnaire
                    encoded_data = {var_to_bytes(key): var_to_bytes(elem) for key, elem in data.items()}

                    # Insertion des données
                    batch.put(key, encoded_data)

        # Fermeture du client HBase
        connection.close()

        print("Données chargées avec succès")

    # Extraction des données brutes
    raw_dict = extract()

    # Transformation des données brutes pour ne garder que ce qui nous intéresse
    transformed_dicts = transform(raw_dict)

    # Chargement des données
    load(earthquakes_list=transformed_dicts)


# Lancement du DAG général
earthquake_etl_hbase()
