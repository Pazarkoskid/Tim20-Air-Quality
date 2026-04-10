const { Pool } = require("pg");

const pool = new Pool({
  user: "postgres",
  host: "localhost",
  database: "airquality",
  password: "your_password",
  port: 5432,
});

pool.on("connect", () => {
  console.log("Connected to PostgreSQL database");
});

pool.on("error", (err) => {
  console.error("Unexpected error on idle client", err);
  process.exit(-1);
});

// Create tables if they don't exist
pool.query(`
  CREATE TABLE IF NOT EXISTS Users (
    id SERIAL PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT
  )
`, (err, res) => {
  if (err) {
    console.error("Error creating Users table:", err);
  } else {
    console.log("Users table ready");
  }
});

pool.query(`
  CREATE TABLE IF NOT EXISTS Air_Quality (
    id SERIAL PRIMARY KEY,
    location TEXT,
    pm10 REAL,
    pm2_5 REAL,
    co REAL,
    no2 REAL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )
`, (err, res) => {
  if (err) {
    console.error("Error creating Air_Quality table:", err);
  } else {
    console.log("Air_Quality table ready");
  }
});

pool.query(`
  CREATE TABLE IF NOT EXISTS Predictions (
    id SERIAL PRIMARY KEY,
    location TEXT,
    predicted_aqi REAL,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )
`, (err, res) => {
  if (err) {
    console.error("Error creating Predictions table:", err);
  } else {
    console.log("Predictions table ready");
  }
});

module.exports = pool;
