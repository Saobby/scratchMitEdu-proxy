import requests
import brotli
from flask import *
from flask_compress import Compress
import re
import hashlib
import time
import redis_api

app = Flask(__name__, static_url_path="/__scratch_proxy_static__")
Compress(app)

domain = "aranara.saobby.com"  # your domain
domain_re = "^(.+\\.)?{}$".format(domain.replace(".", "\\."))
domain_sub_re = "{}$".format(domain.replace(".", "\\."))
scratch_domain = "scratch.mit.edu"
cache_dir = "cache/"  # cache folder
if cache_dir[-1] != "/":
    cache_dir += "/"


@app.route("/", methods=["get", "post", "delete", "put", "head", "connect", "options", "trace", "patch"])
def index():
    return proxy()


@app.route("/<path:path>", methods=["get", "post", "delete", "put", "head", "connect", "options", "trace", "patch"])
def doc(path):
    return proxy()


def check_content_type(content_type):
    if content_type is None:
        return False
    l = ["text", "json", "javascript", "xml"]
    for e in l:
        if e in content_type:
            return True
    return False


def get_md5(sth: str):
    return hashlib.md5(sth.encode("utf-8")).hexdigest()


def get_cache_args(cache_control):
    lst = cache_control.replace(" ", "").split(",")
    ret = {}
    for i in lst:
        if "=" in i:
            ret[i.split("=")[0]] = i.split("=")[1]
        else:
            ret[i] = None
    return ret


def gen_cache_control(args):
    ret = []
    for k, v in args.items():
        if v is None:
            ret.append(k)
        else:
            ret.append("{}={}".format(k, v))
    return ",".join(ret)


def proxy():
    if re.match(domain_re, request.host) is None:
        return abort(400)
    if request.method.lower() == "options":
        return b"", 204
    target_domain = re.sub(domain_sub_re, scratch_domain, request.host)
    target_url = "https://{}{}".format(target_domain, request.full_path)
    if target_url[-1] == "?":
        target_url = target_url[:-1]
    req_headers = {k: v for k, v in request.headers.items()}
    req_headers["Host"] = target_domain
    if "Referer" in req_headers:
        req_headers["Referer"] = req_headers["Referer"].replace(domain, scratch_domain)
    if "Origin" in req_headers:
        req_headers["Origin"] = req_headers["Origin"].replace(domain, scratch_domain)
    if "Etag" in req_headers:
        req_headers["Etag"] = re.sub(":[A-Z,a-z,0-9]+", "", req_headers["Etag"], 1)
    if "If-None-Match" in req_headers:
        req_headers["If-None-Match"] = re.sub(":[A-Z,a-z,0-9]+", "", req_headers["If-None-Match"], 1)
    db_session = redis_api.get_session()
    obj_key = get_md5(target_url)
    redis_key = "scratch_proxy_cache_{}".format(obj_key)
    cache_info = db_session.get(redis_key)
    db_session.close()
    if cache_info is not None:
        cache_info = json.loads(cache_info)
        etag = req_headers.get("If-None-Match")
        if etag is None:
            etag = req_headers.get("Etag")
        modify_time = req_headers.get("If-Modified-Since")
        rep_headers = {}
        rep_headers["Age"] = "0"
        cache_args = get_cache_args(cache_info["cache_control"])
        ts = time.time()
        cache_args["max-age"] = int(cache_info["max_age"] - (ts - cache_info["cache_time"]))
        rep_headers["Cache-Control"] = gen_cache_control(cache_args)
        rep_headers["Etag"] = cache_info["etag"]
        rep_headers["X-Saobby-Cache"] = "hit, max-age={}, age={}".format(cache_info["max_age"], int(ts - cache_info["cache_time"]))
        if etag is not None:
            if etag == cache_info["etag"] and modify_time == cache_info["modify_time"]:
                return b"", 304, rep_headers
        rep_headers["Content-Type"] = cache_info["content_type"]
        rep_headers["Last-Modified"] = cache_info["modify_time"]
        return send_file(cache_dir+obj_key), 200, rep_headers
    rep = requests.request(request.method.lower(), target_url, headers=req_headers, data=request.data, allow_redirects=False)
    rep_content = rep.content
    rep_headers = rep.headers.copy()
    rep_code = rep.status_code
    if check_content_type(rep_headers.get("Content-Type")):
        rep_content = rep.text.replace(scratch_domain, domain)
    if rep_headers.get("Cache-Control") is not None and rep_code == 200 and "Set-Cookie" not in rep_headers:
        if "public" in rep_headers["Cache-Control"] and "max-age" in rep_headers["Cache-Control"]:
            cache_args = get_cache_args(rep_headers["Cache-Control"])
            if int(cache_args["max-age"]) != 0:
                obj_key = get_md5(target_url)
                if isinstance(rep_content, bytes):
                    with open(cache_dir+obj_key, "wb") as f:
                        f.write(rep_content)
                else:
                    with open(cache_dir+obj_key, "w", encoding="utf-8") as f:
                        f.write(rep_content)
                db_session = redis_api.get_session()
                age = rep_headers.get("Age")
                if age is None:
                    age = 0
                age = int(age)
                max_age = int(cache_args["max-age"])
                cache_info = {"etag": rep_headers.get("Etag"), "cache_time": time.time(),
                              "max_age": int(max_age-age), "content_type": rep_headers.get("Content-Type"),
                              "modify_time": rep_headers.get("Last-Modified"),
                              "cache_control": rep_headers["Cache-Control"]}
                redis_key = "scratch_proxy_cache_{}".format(obj_key)
                db_session.set(redis_key, json.dumps(cache_info))
                db_session.expire(redis_key, int(max_age-age))
                db_session.close()
                rep_headers["X-Saobby-Cache"] = "miss"
            else:
                rep_headers["X-Saobby-Cache"] = "dynamic"
        else:
            rep_headers["X-Saobby-Cache"] = "private"
    else:
        rep_headers["X-Saobby-Cache"] = "dynamic"

    if "Transfer-Encoding" in rep_headers:
        del rep_headers["Transfer-Encoding"]
    if "Connection" in rep_headers:
        del rep_headers["Connection"]
    if "Vary" in rep_headers:
        del rep_headers["Vary"]
    if "Content-Encoding" in rep_headers:
        del rep_headers["Content-Encoding"]
    if "Location" in rep_headers:
        rep_headers["Location"] = rep_headers["Location"].replace(scratch_domain, domain)
    cookies = []
    if "Set-Cookie" in rep_headers:
        cookies = rep.raw.headers.getlist("Set-Cookie")
        del rep_headers["Set-Cookie"]
    rep_headers = [(k, v) for k, v in rep_headers.items()]
    for cookie in cookies:
        rep_headers.append(("Set-Cookie", cookie.replace(scratch_domain, domain)))
    return rep_content, rep_code, rep_headers


@app.after_request
def add_header(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    if request.headers.get("Origin") is not None:
        r.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin")
    r.headers["Access-Control-Allow-Headers"] = "x-requested-with,x-token,accept-language,x-csrftoken,accept,accept-version,content-type,request-id,origin,x-api-version,x-request-id"
    r.headers["Access-Control-Allow-Credentials"] = "true"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,PUT,HEAD,CONNECT,OPTIONS,TRACE,PATCH"
    r.headers["Access-Control-Max-Age"] = "600"
    r.headers["Access-Control-Expose-Headers"] = "*"
    return r


@app.errorhandler(400)
def error_400(err):
    return b"", 400


@app.errorhandler(404)
def error_404(err):
    return b"", 404


@app.errorhandler(500)
def error_500(err):
    return b"", 500


if __name__ == "__main__":
    app.run(port=8877)
