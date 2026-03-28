class Prediction {
    constructor(id, location, predicted_aqi, date) {
        this.id = id;
        this.location = location;
        this.predicted_aqi = predicted_aqi;
        this.date = date;
    }
}

module.exports = Prediction;