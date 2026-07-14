# Task Retry and Run Guard Design

## Goal

Allow every registered task to configure how many times a failed run is retried. The default is two retries. Prevent the same task from running more than once at a time.

## Scope

The setting applies to all task triggers: scheduled, manual, and manual runs that send a Telegram notification. It controls failures caused by non-zero exit codes, timeouts, and process-start exceptions. A value of `2` means one initial attempt plus at most two additional attempts.

## Configuration and API

Each task stores its retry count in the existing per-task settings namespace as `task.<task_id>.retry_count`.

- Missing values resolve to `2`.
- Saved values must be integers from `0` through `10`; invalid values return an HTTP 400 response.
- The existing task schedule API accepts `retry_count` and returns its effective value in the task schedule/card payload.
- The schedule dialog adds a numeric input labelled `失败后重试次数`, initialized to the effective value.

## Execution

`TaskRunner` executes the task command until it succeeds or exhausts `retry_count + 1` attempts. It aggregates output in the final run record with an explicit per-attempt header, preserving each failed attempt's stdout/stderr for diagnosis. Notifications and result parsing use the final outcome only, so an initial failure that later succeeds does not notify as a failure.

No delay or retry classification is added: all existing failure kinds receive the same immediate retry behavior. This keeps the setting predictable and avoids adding a policy the user did not request.

## Overlap Guard

`TraeclawApp.run_task` maintains an in-memory, lock-protected set of currently running task IDs. A second request for the same task returns a failed result with a clear `already running` summary and does not create a second subprocess or run record. The guard is released in `finally`, including when the runner itself raises.

The guard is process-local, matching the current single-process scheduler/server architecture. Scheduler requests already run in background threads; manual API requests use the same guard.

## Testing

Tests cover the default and customized retry configuration through the API, validation of bad settings, successful retry after a failure, exhaustion after the configured retry count, timeout retry, and overlap rejection while the first task is still running. The existing full pytest suite remains the regression gate.
