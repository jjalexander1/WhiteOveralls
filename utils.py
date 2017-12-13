import os
import dotenv


def load_env_from_env_file():
    env_file = os.environ.get('ENV_FILE', None)
    dotenv.load_dotenv(env_file, verbose=True)
