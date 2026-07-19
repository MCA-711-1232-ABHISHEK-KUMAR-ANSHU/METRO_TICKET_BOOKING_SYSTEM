-- =====================================================
-- METRO TICKET BOOKING SYSTEM - DATABASE SCHEMA
-- =====================================================

CREATE DATABASE IF NOT EXISTS metro_db;
USE metro_db;

-- ---------------------------------------------------
-- USERS (login accounts - passenger or admin)
-- ---------------------------------------------------
CREATE TABLE user (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'passenger'   -- 'passenger' or 'admin'
);

-- ---------------------------------------------------
-- PASSENGER PROFILE
-- ---------------------------------------------------
CREATE TABLE passenger (
    passenger_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(15),

    CONSTRAINT fk_passenger_user
        FOREIGN KEY (user_id)
        REFERENCES user(user_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------
-- STATIONS
-- ---------------------------------------------------
CREATE TABLE station (
    station_id INT AUTO_INCREMENT PRIMARY KEY,
    station_name VARCHAR(100) NOT NULL,
    location VARCHAR(100)
);

-- ---------------------------------------------------
-- ROUTES  (admin defines a route between two stations
-- along with the fare a passenger pays for that route)
-- ---------------------------------------------------
CREATE TABLE route (
    route_id INT AUTO_INCREMENT PRIMARY KEY,
    route_name VARCHAR(100) NOT NULL,
    start_station INT NOT NULL,
    end_station INT NOT NULL,
    fare INT NOT NULL DEFAULT 0,

    CONSTRAINT fk_route_start
        FOREIGN KEY (start_station)
        REFERENCES station(station_id),

    CONSTRAINT fk_route_end
        FOREIGN KEY (end_station)
        REFERENCES station(station_id)
);

-- ---------------------------------------------------
-- TICKETS
-- ---------------------------------------------------
CREATE TABLE ticket (
    ticket_id INT AUTO_INCREMENT PRIMARY KEY,
    passenger_id INT NOT NULL,
    from_station INT NOT NULL,
    to_station INT NOT NULL,
    travel_date DATE NOT NULL,
    fare INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'BOOKED',  -- BOOKED / CANCELLED / USED
    booked_on DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_ticket_passenger
        FOREIGN KEY (passenger_id)
        REFERENCES passenger(passenger_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_ticket_from_station
        FOREIGN KEY (from_station)
        REFERENCES station(station_id),

    CONSTRAINT fk_ticket_to_station
        FOREIGN KEY (to_station)
        REFERENCES station(station_id)
);

-- ---------------------------------------------------
-- PAYMENTS
-- ---------------------------------------------------
CREATE TABLE payment (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id INT NOT NULL,
    amount INT NOT NULL,
    payment_method VARCHAR(50),
    payment_status VARCHAR(50),

    CONSTRAINT fk_payment_ticket
        FOREIGN KEY (ticket_id)
        REFERENCES ticket(ticket_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------
-- CANCELLATIONS / COMPENSATION
-- ---------------------------------------------------
CREATE TABLE cancellation (
    cancellation_id INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id INT NOT NULL,
    reason VARCHAR(255),
    refund_amount INT NOT NULL,
    cancelled_on DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_cancellation_ticket
        FOREIGN KEY (ticket_id)
        REFERENCES ticket(ticket_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------
-- FEEDBACK (logged-in passenger)
-- ---------------------------------------------------
CREATE TABLE feedback (
    feedback_id INT AUTO_INCREMENT PRIMARY KEY,
    passenger_id INT NOT NULL,
    message VARCHAR(500) NOT NULL,
    rating INT,
    submitted_on DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_feedback_passenger
        FOREIGN KEY (passenger_id)
        REFERENCES passenger(passenger_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------
-- CONTACT US MESSAGES (public, no login required)
-- ---------------------------------------------------
CREATE TABLE contact_message (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    subject VARCHAR(150),
    message VARCHAR(500) NOT NULL,
    submitted_on DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- SEED DATA
-- =====================================================

INSERT INTO station (station_name, location) VALUES
('Danapur', 'Patna'),
('Saguna More', 'Patna'),
('RPS More', 'Patna'),
('Bailey Road', 'Patna'),
('Rukanpura', 'Patna'),
('Raja Bazar', 'Patna'),
('Patliputra', 'Patna'),
('Rajiv Nagar', 'Patna'),
('Ashiana More', 'Patna'),
('Boring Road', 'Patna'),
('Patna Junction', 'Patna'),
('Income Tax Golambar', 'Patna'),
('Gandhi Maidan', 'Patna'),
('Dak Bungalow', 'Patna'),
('Exhibition Road', 'Patna'),
('Mithapur Bus Stand', 'Patna'),
('Kankarbagh', 'Patna'),
('Malahi Pakri', 'Patna'),
('Zero Mile', 'Patna'),
('New ISBT', 'Patna');

-- A few sample routes with fares set by admin (Danapur(1) -> New ISBT(20) line)
INSERT INTO route (route_name, start_station, end_station, fare) VALUES
('Danapur - Patna Junction', 1, 11, 25),
('Patna Junction - New ISBT', 11, 20, 20),
('Danapur - New ISBT (Full Line)', 1, 20, 40);

-- Default admin login -> email: admin@metro.com / password: admin123
-- (the value below is a Werkzeug generate_password_hash() of 'admin123')
INSERT INTO user (username, email, password, role) VALUES
('admin', 'admin@metro.com', 'scrypt:32768:8:1$lmNlF0oImNHJ5cou$0ff77d4111b67ca7ee901280a5a1323b37b60fc9c488ca498a0aba660d9553711a535919e8b20537e929fc6298a5a2ef68367f6163c29cdb11590715339636a1', 'admin');
