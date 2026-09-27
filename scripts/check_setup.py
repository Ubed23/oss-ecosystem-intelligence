from dotenv import load_dotenv
import os, requests

load_dotenv()
h = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]}

rl = requests.get("https://api.github.com/rate_limit", headers=h).json()
print("core   ", rl["resources"]["core"]["remaining"], "/", rl["resources"]["core"]["limit"])
print("graphql", rl["resources"]["graphql"]["remaining"], "/", rl["resources"]["graphql"]["limit"])

b = requests.get("https://api.github.com/repositories/53548867", headers=h).json()
print(b["full_name"], "|", str(b["description"])[:70])