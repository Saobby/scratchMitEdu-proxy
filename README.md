# scratchMitEdu-proxy
 Reverse proxy for https://scratch.mit.edu
# How to use
1. Add domain name resolution
  - `proxy.example.com` -> `{yourServerIP}`
  - `*.proxy.example.com` -> `{yourServerIP}`
2. deploy this program on a server that can access `https://scratch.mit.edu` (Please make sure that HTTPS is supported)
3. set your redis server address and port in `redis_api.py`
4. set your domain name and cache folder in `server.py`
5. enjoy
