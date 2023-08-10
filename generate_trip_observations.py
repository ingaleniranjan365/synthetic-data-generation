import math
import random
from datetime import timedelta
from functools import reduce

from pyspark.sql import SparkSession
from pyspark.sql.functions import rand
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType, TimestampType


def get_spark_session() -> SparkSession:
    return SparkSession.builder \
        .appName("NYCTaxiTripObservationGenerator") \
        .config("spark.executor.memory", "12g") \
        .config("spark.driver.memory", "4g") \
        .config("spark.default.parallelism", 8) \
        .getOrCreate()


def get_columns():
    return [
        StructField("id", StringType(), True),
        StructField("vendor_id", IntegerType(), True),
        StructField("pickup_datetime", TimestampType(), True),
        StructField("dropoff_datetime", TimestampType(), True),
        StructField("passenger_count", IntegerType(), True),
        StructField("pickup_longitude", DoubleType(), True),
        StructField("pickup_latitude", DoubleType(), True),
        StructField("dropoff_longitude", DoubleType(), True),
        StructField("dropoff_latitude", DoubleType(), True),
        StructField("store_and_fwd_flag", StringType(), True),
        StructField("trip_duration", IntegerType(), True)
    ]


def get_new_columns():
    return [
        StructField("long", DoubleType(), True),  # Renamed from obs_longitude to long
        StructField("lat", DoubleType(), True),  # Renamed from obs_latitude to lat
        StructField("timestamp", TimestampType(), True)  # Renamed from obs_timestamp to timestamp
    ]


def get_schema():
    return StructType(get_columns())


def get_observations_schema():
    return StructType(get_columns() + get_new_columns())


def generate_dummy_records(row, min_obs_cnt, max_obs_cnt):
    obs_cnt = random.randint(min_obs_cnt, max_obs_cnt)
    obs_records = []
    obs_records.append((row['id'], row['vendor_id'], row['pickup_datetime'], None, row['passenger_count'],
                        row['pickup_longitude'], row['pickup_latitude'], None, None,
                        row['store_and_fwd_flag'], row['trip_duration'], row['pickup_longitude'],
                        row['pickup_latitude'], row['pickup_datetime']))

    for _ in range(obs_cnt):
        obs_longitude = random.uniform(row['pickup_longitude'], row['dropoff_longitude'])
        obs_latitude = random.uniform(row['pickup_latitude'], row['dropoff_latitude'])
        obs_timestamp = row['pickup_datetime'] + timedelta(
            seconds=random.randint(0, int((row['dropoff_datetime'] - row['pickup_datetime']).total_seconds())))

        obs_records.append((row['id'], row['vendor_id'], row['pickup_datetime'], None, row['passenger_count'],
                            row['pickup_longitude'], row['pickup_latitude'], None, None,
                            row['store_and_fwd_flag'], row['trip_duration'], obs_longitude, obs_latitude,
                            obs_timestamp))

    obs_records.append(
        (row['id'], row['vendor_id'], row['pickup_datetime'], row['dropoff_datetime'], row['passenger_count'],
         row['pickup_longitude'], row['pickup_latitude'], row['dropoff_longitude'], row['dropoff_latitude'],
         row['store_and_fwd_flag'], row['trip_duration'], row['dropoff_longitude'], row['dropoff_latitude'],
         row['dropoff_datetime']))

    return obs_records


def partition_integer(value):
    partitions = []
    while value > 0:
        partition = min(value, 10000)
        partitions.append(partition)
        value -= partition
    return partitions


MIN_OBSERVATIONS_CNT = 5
MAX_OBSERVATIONS_CNT = 200
TRIP_CNT = 100000

if __name__ == '__main__':
    spark = get_spark_session()

    input_path = "data/nyc-taxi-trip-duration/train.csv"
    output_path = "data/shuffled_observations_csv"
    trips_df = spark.read.csv(input_path, header=True, schema=get_schema()).limit(TRIP_CNT)
    num_splits = math.ceil(TRIP_CNT / 5000)
    trips_split_df = trips_df.randomSplit([1.0 / num_splits] * num_splits)
    observation_dfs = []

    for df in trips_split_df:
        observation_rows = []
        for row in df.collect():
            observation_rows.extend(generate_dummy_records(row, MIN_OBSERVATIONS_CNT, MAX_OBSERVATIONS_CNT))
        observations_df = spark.createDataFrame(observation_rows, schema=get_observations_schema()) \
            .withColumn("order", rand()) \
            .orderBy(["id", "order"])

        observation_dfs.append(observations_df)

    all_observations_df = reduce(lambda df1, df2: df1.union(df2), observation_dfs)

    all_observations_df.coalesce(1).select([col for col in all_observations_df.columns if col != "order"]).write.csv(
        output_path, header=True,
        mode="overwrite")

    spark.stop()