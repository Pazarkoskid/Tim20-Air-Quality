from flask import Flask, jsonify
import requests

app = Flask(__name__)

@app.route("/")
def home():
    return "Air Quality API Running"

@app.route("/air-quality")
def get_air_quality():
    url = "http://api.openweathermap.org/data/2.5/air_pollution?lat=41.9981&lon=21.4254&appid=7fbee9cf31b0b06d00f62d1200a954e5"
    response = requests.get(url)
    return jsonify(response.json())

if __name__ == "__main__":
    app.run(debug=True)