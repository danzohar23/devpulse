CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS commits (
    sha          VARCHAR(40)   PRIMARY KEY,
    repo         VARCHAR(255)  NOT NULL,
    message      TEXT          NOT NULL,
    author_name  VARCHAR(255)  NOT NULL,
    author_email VARCHAR(255)  NOT NULL,
    timestamp    TIMESTAMPTZ   NOT NULL,
    url          VARCHAR(1024) NOT NULL,
    embedding    vector(1536)
);

CREATE INDEX IF NOT EXISTS commits_repo_idx       ON commits (repo);
CREATE INDEX IF NOT EXISTS commits_timestamp_idx  ON commits (timestamp DESC);

CREATE TABLE IF NOT EXISTS pull_requests (
    pr_id      INTEGER       NOT NULL,
    repo       VARCHAR(255)  NOT NULL,
    title      VARCHAR(1024) NOT NULL,
    body       TEXT          NOT NULL,
    state      VARCHAR(50)   NOT NULL,
    merged_at  TIMESTAMPTZ,
    created_at TIMESTAMPTZ   NOT NULL,
    url        VARCHAR(1024) NOT NULL,
    embedding  vector(1536),
    PRIMARY KEY (pr_id, repo)
);

CREATE INDEX IF NOT EXISTS pull_requests_repo_idx       ON pull_requests (repo);
CREATE INDEX IF NOT EXISTS pull_requests_created_at_idx ON pull_requests (created_at DESC);

CREATE TABLE IF NOT EXISTS issues (
    issue_id   INTEGER       NOT NULL,
    repo       VARCHAR(255)  NOT NULL,
    title      VARCHAR(1024) NOT NULL,
    body       TEXT          NOT NULL,
    state      VARCHAR(50)   NOT NULL,
    created_at TIMESTAMPTZ   NOT NULL,
    closed_at  TIMESTAMPTZ,
    url        VARCHAR(1024) NOT NULL,
    embedding  vector(1536),
    PRIMARY KEY (issue_id, repo)
);

CREATE INDEX IF NOT EXISTS issues_repo_idx       ON issues (repo);
CREATE INDEX IF NOT EXISTS issues_created_at_idx ON issues (created_at DESC);
