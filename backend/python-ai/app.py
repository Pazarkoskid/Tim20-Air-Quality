from flask import Flask, jsonify
import requests

app = Flask(__name__)

API_KEY = "7fbee9cf31b0b06d00f62d1200a954e5"
LAT, LON = 41.9981, 21.4254

@app.route("/")
def home():
    return "Air Quality API Running"

@app.route("/air-quality")
def get_air_quality():
    url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={LAT}&lon={LON}&appid={API_KEY}"
    response = requests.get(url)
    return jsonify(response.json())

@app.route("/predict")
def predict():
    url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={LAT}&lon={LON}&appid={API_KEY}"
    response = requests.get(url)
    current_data = response.json()

    current_aqi = current_data["list"][0]["main"]["aqi"]

    # 3. TODO: replace this with your real ML model prediction
    predicted_aqi = current_aqi 

    return jsonify({
        "current_aqi": current_aqi,
        "prediction_24h": predicted_aqi,
        "location": "Skopje"
    })

if __name__ == "__main__":
    app.run(debug=True)