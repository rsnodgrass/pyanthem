""" Read the configuration for supported devices """
import os
import yaml
import logging

LOG = logging.getLogger(__name__)

DEVICE_CONFIG = {}
PROTOCOL_CONFIG = {}

def _load_config(config_file):
    """Load the amp series configuration"""

    print(f"Loading {config_file}")
    LOG.info(f"Loading {config_file}")
    with open(config_file, 'r') as stream:
        try:
            return yaml.load(stream, Loader=yaml.FullLoader)
        except yaml.YAMLError as exc:
            LOG.error(f"Failed reading config {config_file}: {exc}")
            return None

def _load_config_dir(directory):
    config_tree = {}

    for filename in os.listdir(directory):
        if filename.endswith('.yaml'):
            series = filename.split('.yaml')[0]
            config = _load_config(os.path.join(directory, filename))
            if config:
                config_tree[series] = config

    return config_tree

def get_with_log(name, dictionary, key: str):
    value = dictionary.get(key)
    if value:
        return dictionary.get(key)
    LOG.warning(f"Invalid key '{key}' in dictionary '{name}'; returning None")
    return None

config_dir = os.path.dirname(__file__)
DEVICE_CONFIG = _load_config_dir(f"{config_dir}/series")
PROTOCOL_CONFIG = _load_config_dir(f"{config_dir}/protocols")
