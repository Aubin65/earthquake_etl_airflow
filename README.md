# Projet d'ETL via l'API d'enregistrement des tremblements de terre - Version Airflow

![Earthquake](images/earthquake.png)

## Contexte :

Pour ce mini-projet, j'ai décidé de requêter l'[API](https://earthquake.usgs.gov/fdsnws/event/1/) du gouverment américain afin de tester l'aspect planification d'Apache Airflow. En effet, l'ETL viendra requêter l'API toutes les minutes et stockera les informations qui n'ont pas encore été stockées dans une base de donnée locale (MongoDB, HBase ou Cassandra). La fonction de purge, quant à elle, viendra automatiquement purger les données qui sont plus anciennes avec les paramètres convenus. Un troisième flow servira à alerter une liste de mails lorsque des séismes apparaissent trop proches de notre position (nous prendrons arbitrairement Orthez)

## Prérequis :

* Un [environnement virtuel](https://docs.python.org/3/library/venv.html)
* Une configuration [Apache Airflow](https://airflow.apache.org/)
  * Cela implique la configuration du fichier airflow.cfg avec notamment la définition de la *dags_folder*
* Une configuration :
  * [MongoDB](https://www.mongodb.com/) pour les [DAGs MongoDB](https://github.com/Aubin65/earthquake_etl_airflow/tree/main/DAGs/mongodb)
  * [HBase](https://hbase.apache.org/) pour les [DAGs HBase](https://github.com/Aubin65/earthquake_etl_airflow/tree/main/DAGs/hbase/workflows)
  * [Cassandra](https://cassandra.apache.org/doc/3.11/cassandra/getting_started/installing.html) pour les [DAGs Cassandra](https://github.com/Aubin65/earthquake_etl_airflow/tree/main/DAGs/cassandra)
* Une configuration de mail (Outlook ici mais fonctionne avec d'autres services)

## Structure :

Le projet est, comme précédemment décrit, structuré en trois DAGs (workflows) pour chaque type de bases de données :
* Un DAG d'ETL
* Un DAG de purge
* Un DAG d'alerte

## ETL :

Comme décrit précédemment, l'ETL va venir requêter l'[API](https://earthquake.usgs.gov/fdsnws/event/1/) du gouverment américain pour récupérer les données dont nous avons besoin.

Les transformations effectuées sont :
* Une sélection spécifique des données
* Un changement du format de la date : timestamp -> UTC
* Une séparation des différents composants de la géolocalisation
* L'ajout de l'attribut *distance_from_us_km* qui contient la distance entre l'épicentre du séisme et Orthez

Ci-dessous sont répertoriées les formes de stockage des données dans chaque type de SGBD :

### MongoDB : 

Dans le cas de la base de données **MongoDB**, les données sont stockées de la manière suivante :

```json
{
  "_id": "ObjectId('674597b629fb05cd930292bf')",
  "mag": 1.32,
  "place": "9 km NW of The Geysers, CA",
  "date": "2024-11-26T09:21:32",
  "type": "earthquake",
  "nst": 27,
  "dmin": 0.007061,
  "sig": 27,
  "magType": "md",
  "geometryType": "Point",
  "longitude": -122.842666625977,
  "latitude": 38.8193321228027,
  "depth": 2.46000003814697,
  "distance_from_us_km": 9194.42
}
```

Dans ce cas spécifique, j'ai décidé d'utiliser la librairie **pymongo** de python mais j'aurais pu choisir un **MongoHook** spécifique à Airflow.

### HBase : 

Dans le cas de la base de données **HBase**, les données sont stockées de la manière suivante : 

![Output HBase](images/hbase_printing.png)

Les données sont nécessairement stockées en binaire dans ce système de gestion de bases de données.

### Cassandra : 

Dans le cas de la base de données **Cassandra**, les données sont stockées de la manière suivante :

## Purge :

L'un des défis pour ne pas surcharger ni la base de données, ni les visuels, est de ne pas récupérer l'historique des données mais seulement une journée de données. Pour cela, nous récupérons les données lorsqu'elles apparaissent, puis nous purgeons celles qui datent de plus de 24h.

La visée de ce projet est d'avoir une base de données recueillant seulement les données très récentes sur les tremblements de terre. D'autres utilisations de l'API pourraient mener à des rapports historiques concernant les statistiques collectées mais ce n'est pas le but de ce projet de test.

## Alerting :

Le troisième DAG a été mis en place pour alerter les personnes concernées lorsqu'un séisme a eu lieu lors des dernières 24 heures. Le DAG vient récupérer les enregistrements plus proches que la distance minimale déclarée (5000 km par défaut) puis envoie un mail avec leur contenu aux personnes déclarées dans le fichier *.env*.

Pour que ce DAG fonctionne, il faut configurer ce fichier *.env* de la façon suivante : 

```
SMTP_HOST=smtp.office365.com
SMTP_USER=user@mail.com
SMTP_PASSWORD=pwd
SMTP_MAIL_FROM=source@mail.com
SMTP_RECIPIENTS=recipient1@mail.com,recipient2@mail.com
```

## Visualisation :

Il existe dans le répertoire [streamlit](https://github.com/Aubin65/earthquake_etl_airflow/tree/main/streamlit) un [fichier](https://github.com/Aubin65/earthquake_etl_airflow/blob/main/streamlit/streamlit.py) qui permet de visualiser ces tremblements de terre en fonction de leur magnitude. 

Pour lancer ce fichier, il faut se placer dans son répertoire et lancer la ligne de code suivante : 

```bash
streamlit run streamlit.py
```

Ce [dossier](https://github.com/Aubin65/earthquake_etl_airflow/tree/main/streamlit) contient les fonctions permettant la créations des visuels streamlit grâce aux librairies pandas et plotly. Pour lancer ces fonctions, j'ai choisi d'utiliser la base de données MongoDB créée comme décrit dans les parties précédentes.

L'affichage est lui aussi divisé en deux parties : 
* Une partie concernant les tremblements de terre ayant eu lieu durant les 24 dernières heures avec filtre sur la magnitude
* Une partie concernant les n plus proches tremblements de terre parmi ceux précédemment cités

Les rendus sont de la forme suivante : 

<br>
<center>
<img src="images/visuel_earthquakes.png">
<i>Tremblements de terre dans le monde lors des 24 dernières heures</i>
</center>
</br>

<br>
<center>
<img src="images/visuel_earthquakes_proches.png">
<i>n plus proches Tremblements de terre dans le monde lors des 24 dernières heures</i>
</center>
</br>

## Approfondissement du projet :

Pour approfondir ce projet de data engineering, voici deux pistes potentielles : 
* Ajouter d'autres collections qui sont en lien avec celle déjà présente
* Par conséquent ajouter d'autres sources de données pour complexifier la pipeline
* Ajouter un algorithme de clustering pour essayer de retrouver les [23 plaques tectoniques](https://www.notre-planete.info/terre/risques_naturels/seismes/plaques-tectoniques.php) sachant que l'on a leur coordonnées
* Effectuer les mêmes tests de requêtes que pour MongoDB pour les trois types de bases de données