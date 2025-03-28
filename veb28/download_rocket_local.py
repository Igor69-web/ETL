import json
import pathlib
import logging
import requests
import requests.exceptions as requests_exceptions
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.operators.email import EmailOperator
from airflow.utils.dates import days_ago

# Функция для скачивания изображений
def _get_pictures():
    images_dir = "/opt/airflow/data/images"
    pathlib.Path(images_dir).mkdir(parents=True, exist_ok=True)

    try:
        with open("/opt/airflow/data/launches.json") as f:
            launches = json.load(f)
            image_urls = [launch["image"] for launch in launches["results"]]

        for image_url in image_urls:
            response = requests.get(image_url)
            response.raise_for_status()
            image_filename = image_url.split("/")[-1]
            target_file = f"{images_dir}/{image_filename}"
            with open(target_file, "wb") as f:
                f.write(response.content)
            logging.info(f"Downloaded {image_url} to {target_file}")

    except (requests_exceptions.RequestException, json.JSONDecodeError, FileNotFoundError) as e:
        error_message = str(e)
        logging.error(f"Error occurred: {error_message}")
        raise  # Это важно, чтобы Airflow зафиксировал ошибку

# Функция для отправки email при ошибке
def failure_callback(context):
    task_instance = context['task_instance']
    exception = context.get('exception', 'No details available')
    
    # Здесь мы создаем email-оператор для отправки письма
    email_operator = EmailOperator(
        task_id="send_failure_email",
        to=["butsigor123@gmail.com"],
        subject=f"Airflow DAG {context['dag'].dag_id} - Ошибка в задаче {context['task'].task_id}",
        html_content=f"<h3>Ошибка в DAG {context['dag'].dag_id}</h3>"
                     f"<p>Задача: {context['task'].task_id}</p>"
                     f"<p>Ошибка: {exception}</p>",
        dag=context['dag']
    )
    # Выполняем отправку email
    email_operator.execute(context)

# Определение DAG
dag = DAG(
    dag_id="download_rocket_local",
    description="Download rocket pictures of recently launched rockets.",
    start_date=days_ago(14),
    schedule_interval="@daily",
    catchup=False,
    default_args={
        "email_on_failure": False,  # Отключаем стандартное email-уведомление
        "email_on_retry": False,
        "retries": 1,
    },
)

# Операторы
download_launches = BashOperator(
    task_id="download_launches",
    bash_command="curl -f -o /opt/airflow/data/launches.json -L 'https://ll.thespacedevs.com/2.0.0/launch/upcoming' || exit 1",
    dag=dag,
)

get_pictures = PythonOperator(
    task_id="get_pictures",
    python_callable=_get_pictures,
    dag=dag,
    on_failure_callback=failure_callback,  # Вызов email-оповещения при ошибке
)

notify = BashOperator(
    task_id="notify",
    bash_command='echo "There are now $(find /opt/airflow/data/images/ -type f | wc -l) images."',
    dag=dag,
)

# Определяем последовательность выполнения задач
download_launches >> get_pictures >> notify