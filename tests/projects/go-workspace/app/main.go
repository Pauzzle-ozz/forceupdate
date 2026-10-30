// Le programme du workspace : il se sert du module lib.
package main

import (
	"fmt"

	"example.com/ws/lib"
	"github.com/google/uuid"
)

func main() { fmt.Println(lib.Tag, uuid.New()) }
