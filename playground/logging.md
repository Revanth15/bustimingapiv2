Cheat sheet

Exact field value: field:="value"
Field exists: field:*
Search phrase in message: "some phrase"
Parse logfmt message: | unpack_logfmt from _msg
Filter parsed fields: | filter field:="value"
Aggregate: | stats by (field1, field2) count() as logs

All recent /bustiming upstream request errors:

_time:24h "fly.app.name":="bustimingapiv2"
| unpack_logfmt from _msg
| filter event:="lta_api_request_error"

Count those by exception type:

| unpack_logfmt from _msg
| filter event:="lta_api_request_error"
| stats by (exception_type) count() as logs

Only the ConnectionTerminated / RemoteProtocolError cases:

| unpack_logfmt from _msg
| filter event:="lta_api_request_error" AND exception_type:="RemoteProtocolError"

Only retryable upstream failures:

| unpack_logfmt from _msg
| filter event:="lta_api_request_error" AND retryable:="true"

Route-level 503s returned by /bustiming:

| unpack_logfmt from _msg
| filter route:="/bustiming" AND event:="http_error" AND status_code:=503


Cache-hit success logs:

| unpack_logfmt from _msg
| filter event:="success" AND cache_hit:="true"

Count cache hits vs misses:

| unpack_logfmt from _msg
| filter event:="success"
| stats by (cache_hit) count() as logs

Route-level 503s returned by /bustiming:

| unpack_logfmt from _msg
| filter route:="/bustiming" AND event:="http_error" AND status_code:=503

Slow /bustiming requests over 1 second:

| unpack_logfmt from _msg
| filter route:="/bustiming" AND total_ms:> 1000

