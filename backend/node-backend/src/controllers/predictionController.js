const predictionService = require("../services/predictionService");

exports.getPrediction = async (req, res) => {
    try {
        const result = await predictionService.getPredictionData();
        res.json(result);
    } catch (err) {
        res.status(500).json(err);
    }
};