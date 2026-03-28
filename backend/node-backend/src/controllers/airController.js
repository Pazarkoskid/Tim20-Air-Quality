const airService = require("../services/airService");

exports.getAir = async (req, res) => {
    try {
        const result = await airService.getAirData();
        res.json(result);
    } catch (err) {
        res.status(500).json(err);
    }
};