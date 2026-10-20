"""Frozen initial SQLite schema; future schema changes require a new migration."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE TABLE alerts (\n\tid INTEGER NOT NULL, \n\tprediction_id INTEGER NOT NULL, \n\treplay_id VARCHAR NOT NULL, \n\ttime VARCHAR NOT NULL, \n\tprobability DOUBLE NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tacknowledged_at VARCHAR, \n\tPRIMARY KEY (id), \n\tUNIQUE (prediction_id), \n\tFOREIGN KEY(prediction_id) REFERENCES predictions (id), \n\tFOREIGN KEY(replay_id) REFERENCES replays (id)\n)')
    op.execute('CREATE TABLE audit_events (\n\tid INTEGER NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tentity_id VARCHAR NOT NULL, \n\tdetails JSON NOT NULL, \n\tcreated_at VARCHAR NOT NULL, \n\tPRIMARY KEY (id)\n)')
    op.execute('CREATE TABLE model_versions (\n\tid VARCHAR NOT NULL, \n\tpath VARCHAR NOT NULL, \n\tsha256 VARCHAR NOT NULL, \n\tinfo JSON NOT NULL, \n\tcreated_at VARCHAR NOT NULL, \n\tPRIMARY KEY (id)\n)')
    op.execute('CREATE TABLE observed_readings (\n\tid INTEGER NOT NULL, \n\treplay_id VARCHAR NOT NULL, \n\ttime VARCHAR NOT NULL, \n\tglucose DOUBLE NOT NULL, \n\treceived_at VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (replay_id, time), \n\tFOREIGN KEY(replay_id) REFERENCES replays (id)\n)')
    op.execute('CREATE TABLE patients (\n\tid VARCHAR NOT NULL, \n\tsource VARCHAR NOT NULL, \n\tPRIMARY KEY (id)\n)')
    op.execute('CREATE TABLE predictions (\n\tid INTEGER NOT NULL, \n\treplay_id VARCHAR NOT NULL, \n\tmodel_id VARCHAR NOT NULL, \n\ttime VARCHAR NOT NULL, \n\tdue_at VARCHAR NOT NULL, \n\tpopulation_probability DOUBLE NOT NULL, \n\tpersonal_probability DOUBLE NOT NULL, \n\tfeatures JSON NOT NULL, \n\tstate_before JSON NOT NULL, \n\tstate_after JSON, \n\toutcome INTEGER, \n\toutcome_status VARCHAR NOT NULL, \n\tupdated_state INTEGER NOT NULL, \n\tcreated_at VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (replay_id, time), \n\tFOREIGN KEY(replay_id) REFERENCES replays (id), \n\tFOREIGN KEY(model_id) REFERENCES model_versions (id)\n)')
    op.execute('CREATE TABLE recordings (\n\tid VARCHAR NOT NULL, \n\tpatient_id VARCHAR NOT NULL, \n\tprofile JSON NOT NULL, \n\tsource_sha256 VARCHAR NOT NULL, \n\tsummary_sha256 VARCHAR NOT NULL, \n\tsource_name VARCHAR NOT NULL, \n\tstart_time VARCHAR NOT NULL, \n\tend_time VARCHAR NOT NULL, \n\tcount INTEGER NOT NULL, \n\taudit JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(patient_id) REFERENCES patients (id)\n)')
    op.execute('CREATE TABLE replays (\n\tid VARCHAR NOT NULL, \n\trecording_id VARCHAR NOT NULL, \n\tmodel_id VARCHAR NOT NULL, \n\tcursor INTEGER NOT NULL, \n\tstate JSON NOT NULL, \n\tvirtual_time VARCHAR, \n\tcreated_at VARCHAR NOT NULL, \n\tupdated_at VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(recording_id) REFERENCES recordings (id), \n\tFOREIGN KEY(model_id) REFERENCES model_versions (id)\n)')
    op.execute('CREATE TABLE source_readings (\n\tid INTEGER NOT NULL, \n\trecording_id VARCHAR NOT NULL, \n\tposition INTEGER NOT NULL, \n\ttime VARCHAR NOT NULL, \n\tglucose DOUBLE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (recording_id, position), \n\tUNIQUE (recording_id, time), \n\tFOREIGN KEY(recording_id) REFERENCES recordings (id)\n)')
    op.execute('CREATE INDEX ix_alerts_replay_id ON alerts (replay_id)')
    op.execute('CREATE INDEX ix_audit_events_kind ON audit_events (kind)')
    op.execute('CREATE INDEX ix_observed_readings_replay_id ON observed_readings (replay_id)')
    op.execute('CREATE INDEX ix_predictions_replay_id ON predictions (replay_id)')
    op.execute('CREATE INDEX ix_recordings_patient_id ON recordings (patient_id)')
    op.execute('CREATE INDEX ix_source_readings_recording_id ON source_readings (recording_id)')


def downgrade():
    raise RuntimeError("Destructive downgrade disabled. Restore a backup instead.")
