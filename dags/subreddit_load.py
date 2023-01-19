from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pandas as pd
import praw
from dotenv import dotenv_values
from helpers import util

from airflow import DAG
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.operators.python import PythonOperator


def get_subreddit_list():
    config = dotenv_values("./api_keys/.env")
    reddit = praw.Reddit(
        client_id=config["REDDIT_CLIENT_ID"],
        client_secret=config["REDDIT_CLIENT_SECRET"],
        user_agent=config["REDDIT_USER_AGENT"],
    )
    wikipage = reddit.subreddit("Music").wiki["musicsubreddits"]
    soup = BeautifulSoup(wikipage.content_html, "html.parser")
    wiki_list = soup.find("div", {"class": "md wiki"})
    bullets = wiki_list.find_all("li")
    all_a = [i.a for i in bullets if i.a is not None]

    subreddits = pd.DataFrame([a["href"] for a in all_a if a["href"].startswith("/r/")])
    subreddits.columns = ["subreddit"]
    subreddits = subreddits.drop_duplicates()
    util.create_dir("output")
    subreddits.to_csv("output/subreddits.csv", index=False)


def export_subreddit_list():
    config = dotenv_values("./api_keys/.env")
    hook = PostgresHook(
        postgres_conn_id="postgres_reddit",
        host="host.docker.internal",
        database="reddit",
        user=config["POSTGRES_USER"],
        password=config["POSTGRES_PASSWORD"],
        port=6543,
    )
    with hook.get_conn() as connection:
        hook.copy_expert(
            """--sql
            copy
              public.subreddits
            from stdin 
            with csv header
            delimiter as ','
        """,
            "output/subreddits.csv",
        )
        connection.commit()


default_args = {"owner": "scott", "retries": 1, "retry_delay": timedelta(seconds=2)}


with DAG(
    dag_id="subreddit_list",
    default_args=default_args,
    start_date=datetime(2022, 12, 29),
    catchup=False,
) as dag:
    task0 = PythonOperator(
        task_id="read_subreddit_list", python_callable=get_subreddit_list
    )

    task1 = PostgresOperator(
        task_id="create_table",
        postgres_conn_id="postgres_reddit",
        sql="""--sql
            create table if not exists subreddits (
              subreddit character varying,
              primary key (subreddit)
            )
            ;""",
    )

    task2 = PostgresOperator(
        task_id="clear_table",
        postgres_conn_id="postgres_reddit",
        sql="""--sql
            truncate table subreddits
            ;""",
    )

    task3 = PythonOperator(
        task_id="export_to_postgres", python_callable=export_subreddit_list
    )

    task0 >> task1 >> task2 >> task3
