import duckdb
import pandas as pd


db_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

con = duckdb.connect(db_path)

def get_headers(path):

    try: 
        header = pd.read_csv(path, nrows = 0)

    except: 
        Print("Invalid path given:" : path)


def create_path(uuid, format, batch):
    query = f"SELECT "Identifier[uuid]", "file_format" FROM TABLE dublin_core_metadata WHERE 
