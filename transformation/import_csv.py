import duckdb

conn = duckdb.connect("/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db")

#duckdb.read_csv('/home/aakash/NIC/Newfolder/nic-metadata-cleaning/nic_sample_dataset.csv')


conn.execute("CREATE TABLE raw_dataset AS FROM '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/sample_datasets_metadata/nic_sample_dataset.csv';")

# if __name__ == "__main__":

#     # duckdb.read_csv('sample_datasets_metadata/nic_sample_dataset.csv')
#     conn.execute("SELECT * FROM dataset LIMIT 10")






