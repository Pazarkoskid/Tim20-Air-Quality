const db = require("../database/db");
const Prediction = require("../models/Prediction");
const { getPredictionFromPython } = require("./pythonService");

exports.getPredictionData = async () => {
    const data = await getPredictionFromPython();

    return new Promise((resolve, reject) => {
        db.run(
            `INSERT INTO Predictions (location, predicted_aqi)
       VALUES (?, ?)`,
            ["Skopje", data.prediction_24h],
            function (err) {
                if (err) return reject(err);

                resolve(
                    new Prediction(this.lastID, "Skopje", data.prediction_24h)
                );
            }
        );
    });
};