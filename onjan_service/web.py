"""Single-process local-network web service with background hardware workers."""
import secrets

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException


def create_app(runtime):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    token = secrets.token_urlsafe(32)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def index():
        return render_template("index.html", token=token, travel=runtime.travel)

    @app.get("/api/status")
    def status():
        return jsonify(runtime.snapshot())

    @app.get('/weight')
    def weight():
        return render_template('weight.html', token=token)

    @app.post("/api/commands/<action>")
    def command(action):
        if request.headers.get("X-Onjan-Token") != token:
            return jsonify(error="페이지를 새로고침하세요."), 403
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400
        try:
            return jsonify(job_id=runtime.submit(action, data)), 202
        except ValueError as exc:
            return jsonify(error=str(exc)), 409

    @app.errorhandler(HTTPException)
    def error(exc):
        return jsonify(error=exc.description), exc.code

    return app
