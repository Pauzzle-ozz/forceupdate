// Un module hors du workspace (pas dans use).
package main

import (
	"fmt"

	"github.com/google/uuid"
)

func main() { fmt.Println(uuid.New()) }
