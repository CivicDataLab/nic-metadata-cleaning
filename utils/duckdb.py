import duckdb
# duckdb.read_csv('sample_datasets_metadata/nic_sample_dataset.csv')

if __name__ == "__main__":

    # duckdb.read_csv('sample_datasets_metadata/nic_sample_dataset.csv')
    duckdb.sql("SELECT * FROM read_csv('sample_datasets_metadata/nic_sample_dataset.csv')")