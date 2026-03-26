const axios = require("axios");

exports.getAirFromPython = async () => {
  const res = await axios.get("http://localhost:5000/air-quality");
  return res.data;
};

exports.getPredictionFromPython = async () => {
  const res = await axios.get("http://localhost:5000/predict");
  return res.data;
};
