#!/usr/bin/env python3
import json, os, sys, urllib.parse
from gremlin_python.driver import client, serializer
from services.shared.cosmos import get_cosmos_config_from_env

config = get_cosmos_config_from_env()
endpoint = config["endpoint"]
key = config["key"]
database = config["database"]
graph = config["graph"]
parsed = urllib.parse.urlparse(endpoint)
endpoint = f"wss://{parsed.netloc}/gremlin"

query = sys.argv[1]
username = f"/dbs/{database}/colls/{graph}"
c = client.Client(endpoint, "g", username=username, password=key, message_serializer=serializer.GraphSONSerializersV2d0())
try:
    rs = c.submit(query)
    result = rs.all().result()
    if isinstance(result, list):
        out = []
        for r in result:
            if isinstance(r, dict):
                out.append({k: (v[0] if isinstance(v, list) else v) for k, v in r.items()})
            else:
                out.append(r)
        print(json.dumps(out, default=str))
    else:
        print(json.dumps(result, default=str))
except Exception as e:
    print(json.dumps({"_error": repr(e), "type": type(e).__name__}), file=sys.stderr)
    sys.exit(1)
finally:
    c.close()
