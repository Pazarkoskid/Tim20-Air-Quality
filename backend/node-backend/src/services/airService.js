const db = require("../database/db");
const AirQuality = require("../models/AirQuality");
const { getAirFromPython } = require("./pythonService");

exports.getAirData = async () => {
    const data = await getAirFromPython();

    return new Promise((resolve, reject) => {
        db.run(
            `INSERT INTO Air_Quality (location, pm10, pm2_5, co, no2)
       VALUES (?, ?, ?, ?, ?)`,
            [data.location, data.pm10, data.pm2_5, data.co, data.no2],
            function (err) {
                if (err) return reject(err);

                resolve(
                    new AirQuality(
                        this.lastID,
                        data.location,
                        data.pm10,
                        data.pm2_5,
                        data.co,
                        data.no2
                    )
                );
            }
        );
    });
};