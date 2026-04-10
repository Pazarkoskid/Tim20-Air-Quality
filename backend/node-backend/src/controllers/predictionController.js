const db = require("../database/db");
const { getPredictionFromPython } = require("../services/pythonService");

exports.getPrediction = async (req, res) => {
  try {
    const data = await getPredictionFromPython();

    await db.query(
      `INSERT INTO Predictions (location, predicted_aqi) VALUES ($1, $2)`,
      ["Skopje", data.prediction_24h]
    );

    res.json(data);
  } catch (err) {
    res.status(500).json(err.message);
  }
};
