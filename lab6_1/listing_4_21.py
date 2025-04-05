from urllib import request
from datetime import datetime, timedelta
from collections import defaultdict

import airflow.utils.dates
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator

dag = DAG(
    dag_id="listing_4_21",
    start_date=datetime(2025, 4, 3, 0, 0),  
    schedule_interval="@hourly",
    template_searchpath="/tmp",
    max_active_runs=1,
    catchup=False,  
)

def _get_data(year, month, day, hour, output_path):
    url = (
        "https://dumps.wikimedia.org/other/pageviews/"
        f"{year}/{year}-{month:0>2}/pageviews-{year}{month:0>2}{day:0>2}-{hour:0>2}0000.gz"
    )
    request.urlretrieve(url, output_path)

def generate_get_data_tasks(dag):
    year = 2025
    month = 4
    day = 4

    tasks = []
    for hour in range(24):
        output_path = f"/tmp/wikipageviews-{hour:0>2}.gz"
        task = PythonOperator(
            task_id=f"get_data_{hour:0>2}",
            python_callable=_get_data,
            op_kwargs={
                "year": year,
                "month": month,
                "day": day,
                "hour": hour,
                "output_path": output_path,
            },
            dag=dag,
            retries=3,
            retry_delay=timedelta(minutes=2), 
            retry_exponential_backoff=True,
        )
        tasks.append(task)
    return tasks

get_data_tasks = generate_get_data_tasks(dag)

extract_gz = BashOperator(
    task_id="extract_gz", 
    bash_command="gunzip --force /tmp/wikipageviews-*.gz", 
    dag=dag,
    retries=3,
    retry_delay=timedelta(minutes=2),
)

def _fetch_pageviews(pagenames, execution_date, **context):
    # Изменяем структуру хранения данных: {(domain, page, hour): views}
    result = defaultdict(int)
    
    for hour in range(24):
        filename = f"/tmp/wikipageviews-{hour:0>2}"
        try:
            data_datetime = datetime(2025, 4, 4, hour)
            
            with open(filename, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) < 4:
                        continue
                    
                    domain_code, page_title, view_counts = parts[0], parts[1], parts[2]
                    
                    if domain_code in ["en", "en.m", "ru", "ru.m"] and page_title in pagenames:
                        # Ключ теперь включает час для разделения периодов
                        result[(domain_code, page_title, hour)] += int(view_counts)
                        
        except FileNotFoundError as e:
            print(f"Error processing file {filename}: {e}")
            continue
                
    with open("/tmp/postgres_query.sql", "w") as f:
        for (domain, pagename, hour), pageviewcount in result.items():
            hour_datetime = datetime(2025, 4, 4, hour)
            f.write(
                "INSERT INTO pageview_counts (domain_name, page_name, view_count, data_period) VALUES ("
                f"""'{domain}', '{pagename.replace("'", "''")}', {pageviewcount}, """
                f"'{hour_datetime.isoformat()}'::timestamp"
                ");\n"
            )

fetch_pageviews = PythonOperator(
    task_id="fetch_pageviews",
    python_callable=_fetch_pageviews,
    op_kwargs={
        "pagenames": {
            "VK_(компания)", "Vkontakte", "VK"
        }
    },
    provide_context=True,
    dag=dag,
    retries=3,
    retry_delay=timedelta(minutes=1),
)

write_to_postgres = PostgresOperator(
    task_id="write_to_postgres",
    postgres_conn_id="my_postgres",
    sql="postgres_query.sql",
    retries=3,
    retry_delay=timedelta(minutes=2),
    dag=dag,
)

for task in get_data_tasks:
    task >> extract_gz

extract_gz >> fetch_pageviews >> write_to_postgres