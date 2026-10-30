module example.com/ws/app

go 1.21

require (
	example.com/ws/lib v0.0.0
	github.com/google/uuid v1.3.0
)

require golang.org/x/text v0.3.7 // indirect

replace example.com/ws/lib => ../lib
