from flask import Flask\napp = Flask(__name__)\n\n@app.route("/api/hello")\ndef hello():\n    return {"message": "Hello!"}
