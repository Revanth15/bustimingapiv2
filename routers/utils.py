import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_env_variable(key: str, required: bool = True) -> str:
    """
    Fetches an environment variable and optionally ensures it is set.
    
    Args:
        key (str): The name of the environment variable.
        required (bool): Whether the variable is required (default: True).
    
    Returns:
        str: The value of the environment variable if set.
    
    Raises:
        ValueError: If the variable is required and not set.
    """
    value = os.getenv(str(key))
    if required and not value:
        raise ValueError(f"{key} is missing in the .env file")
    return value

ACCOUNT_KEY = get_env_variable("ACCOUNT_KEY")

# Query LTA's API
def queryAPI(path, params):
    url = "http://datamall2.mytransport.sg/"
    headers = {
    'AccountKey': ACCOUNT_KEY
    }
    return requests.get(url + path, headers=headers,params=params).json()