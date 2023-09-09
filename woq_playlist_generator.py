"""
Logic for creating a WoQ style quiz
"""
from __future__ import division
from PlaylistGenerator import PlaylistGenerator
import math
import random
import psycopg2
import os
from scraping.utils import load_env_from_env_file

load_env_from_env_file()


def find_poisson(lam, k):
    print((math.e**(-lam))*(lam**(-k))) / (math.factorial(k))


def db_query(query1):
    conn = psycopg2.connect(dbname=os.environ['DB_NAME'],
                            user=os.environ['DB_USER'],
                            password=os.environ['DB_PASSWORD'],
                            host=os.environ['DB_HOST'])
    cur = conn.cursor()
    cur.execute(query1)
    result = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return result



class WoqCreator(PlaylistGenerator):
    def __init__(self):
        super(WoqCreator, self).__init__('WoQ March 2018', results)

current_year = 2017
results = []
for year in range(1952, current_year):
    while True:
        chart_peak = round(random.randrange(0, 5), 0)
        query = """
        SELECT artist, song, week_start_date, chart_peak FROM songbase.song_peaks_mv WHERE chart_peak = {0} AND EXTRACT(YEAR FROM week_start_date) = {1} ORDER BY random() LIMIT 1;
        """.format(chart_peak, year)
        db_result = db_query(query)
        if db_result is not None:
            break
        else:
            db_result = []
    results += db_result

test = PlaylistGenerator('WoQ March 2018', results)
test.generate_playlist()
