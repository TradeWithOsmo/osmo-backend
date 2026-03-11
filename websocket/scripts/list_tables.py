import os
import subprocess

def run_db_query(query):
    cmd = ["docker", "exec", "osmo-db", "psql", "-U", "osmo_user", "-d", "osmo_db", "-c", query]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

if __name__ == "__main__":
    print("--- Tables ---")
    print(run_db_query("\dt"))
    print("--- Recent Messages ---")
    print(run_db_query("SELECT * FROM chat_messages ORDER BY 1 DESC LIMIT 5;"))
