const db = require("../database/db");
const { getAirFromPython } = require("../services/pythonService");

exports.getAir = async (req, res) => {
  try {
    const data = await getAirFromPython();

    db.run(
      `INSERT INTO Air_Quality (location, pm10, pm2_5, co, no2)
       VALUES (?, ?, ?, ?, ?)`,
      [data.location, data.pm10, data.pm2_5, data.co, data.no2],
      function (err) {
        if (err) return res.status(500).json(err.message);

        res.json({
          id: this.lastID,
          ...data,
        });
      },
    );
  } catch (err) {
    res.status(500).json(err.message);
  }
};
