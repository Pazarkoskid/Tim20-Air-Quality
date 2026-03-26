const db = require("../database/db");
const { getPredictionFromPython } = require("../services/pythonService");

exports.getPrediction = async (req, res) => {
  try {
    const data = await getPredictionFromPython();

    db.run(
      `INSERT INTO Predictions (location, predicted_aqi)
       VALUES (?, ?)`,
      ["Skopje", data.prediction_24h],
      function (err) {
        if (err) return res.status(500).json(err.message);

        res.json(data);
      },
    );
  } catch (err) {
    res.status(500).json(err.message);
  }
};
