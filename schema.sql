CREATE TABLE staff (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);
CREATE TABLE rate (
	id INTEGER NOT NULL, 
	vehicle_type VARCHAR(30) NOT NULL, 
	price_per_hour FLOAT NOT NULL, 
	grace_minutes INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vehicle_type)
);
CREATE TABLE slot (
	id INTEGER NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	zone VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);
CREATE TABLE turn_away (
	id INTEGER NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE meta (
	"key" VARCHAR(40) NOT NULL, 
	value VARCHAR(200) NOT NULL, 
	PRIMARY KEY ("key")
);
CREATE TABLE parking_session (
	id INTEGER NOT NULL, 
	plate_number VARCHAR(20) NOT NULL, 
	vehicle_type VARCHAR(30) NOT NULL, 
	slot_id INTEGER NOT NULL, 
	time_in DATETIME NOT NULL, 
	time_out DATETIME, 
	fee FLOAT, 
	status VARCHAR(20) NOT NULL, 
	logged_by INTEGER, 
	voided_at DATETIME, 
	voided_by INTEGER, 
	void_reason VARCHAR(200), 
	PRIMARY KEY (id), 
	FOREIGN KEY(slot_id) REFERENCES slot (id), 
	FOREIGN KEY(logged_by) REFERENCES staff (id), 
	FOREIGN KEY(voided_by) REFERENCES staff (id)
);
CREATE UNIQUE INDEX uq_active_plate ON parking_session (plate_number) WHERE status = 'active';
CREATE UNIQUE INDEX uq_active_slot ON parking_session (slot_id) WHERE status = 'active';
CREATE INDEX ix_parking_session_plate_number ON parking_session (plate_number);
CREATE TABLE audit_event (
	id INTEGER NOT NULL, 
	at DATETIME NOT NULL, 
	staff_id INTEGER, 
	username VARCHAR(50), 
	action VARCHAR(40) NOT NULL, 
	detail VARCHAR(300), 
	PRIMARY KEY (id), 
	FOREIGN KEY(staff_id) REFERENCES staff (id)
);
CREATE INDEX ix_audit_event_at ON audit_event (at);