package main

import (
	"fmt"
	"io"
	"os"

	"github.com/notnil/chess"
)

type GameData struct {
	Pos           *chess.Position
	White         string
	Black         string
	Event         string
	Result        string
	LastMove      *chess.Move
	SAN           string
	MoveNumber    int
	CapturedWhite []chess.PieceType
	CapturedBlack []chess.PieceType
	TotalPlies    int
	IsGameOver    bool
	IsPastEnd     bool
}

func loadPGN(cfg Config) GameData {
	f, err := os.Open(cfg.Input)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error opening PGN: %v\n", err)
		os.Exit(1)
	}
	defer f.Close()

	scanner := chess.NewScanner(f)
	var games []*chess.Game
	for scanner.Scan() {
		game := scanner.Next()
		if game != nil {
			games = append(games, game)
		}
	}

	if err := scanner.Err(); err != nil && err != io.EOF {
		fmt.Fprintf(os.Stderr, "Error parsing PGN: %v\n", err)
		os.Exit(1)
	}

	if len(games) == 0 {
		fmt.Fprintln(os.Stderr, "Error: No games found in PGN")
		os.Exit(1)
	}

	gIdx := cfg.GameIdx - 1
	if gIdx < 0 || gIdx >= len(games) {
		gIdx = 0
	}
	game := games[gIdx]

	moves := game.Moves()
	totalPlies := len(moves)

	plyLimit := totalPlies
	isPastEnd := false

	if cfg.MoveIdx >= 0 {
		if cfg.MoveIdx > totalPlies {
			isPastEnd = true
			plyLimit = totalPlies
		} else {
			plyLimit = cfg.MoveIdx
		}
	}

	isGameOver := (plyLimit == totalPlies)

	replay := chess.NewGame()
	var lastMove *chess.Move
	var san string
	for i := 0; i < plyLimit; i++ {
		lastMove = moves[i]
		san = chess.AlgebraicNotation{}.Encode(replay.Position(), lastMove)
		_ = replay.Move(lastMove)
	}

	data := GameData{
		Pos:        replay.Position(),
		LastMove:   lastMove,
		SAN:        san,
		MoveNumber: (plyLimit + 1) / 2,
		TotalPlies: totalPlies,
		IsGameOver: isGameOver,
		IsPastEnd:  isPastEnd,
	}

	for _, pair := range game.TagPairs() {
		switch pair.Key {
		case "White":
			data.White = pair.Value
		case "Black":
			data.Black = pair.Value
		case "Event":
			data.Event = pair.Value
		case "Result":
			data.Result = pair.Value
		}
	}

	board := replay.Position().Board()
	counts := make(map[chess.Piece]int)
	for sq := chess.A1; sq <= chess.H8; sq++ {
		p := board.Piece(sq)
		if p != chess.NoPiece {
			counts[p]++
		}
	}

	standard := map[chess.Piece]int{
		chess.WhitePawn: 8, chess.WhiteKnight: 2, chess.WhiteBishop: 2, chess.WhiteRook: 2, chess.WhiteQueen: 1,
		chess.BlackPawn: 8, chess.BlackKnight: 2, chess.BlackBishop: 2, chess.BlackRook: 2, chess.BlackQueen: 1,
	}

	data.CapturedWhite = getMissing(counts, standard, chess.White)
	data.CapturedBlack = getMissing(counts, standard, chess.Black)

	return data
}

func getMissing(current, standard map[chess.Piece]int, color chess.Color) []chess.PieceType {
	var missing []chess.PieceType
	order := []chess.PieceType{chess.Queen, chess.Rook, chess.Bishop, chess.Knight, chess.Pawn}
	for _, pt := range order {
		p := chess.NewPiece(pt, color)
		diff := standard[p] - current[p]
		for i := 0; i < diff; i++ {
			missing = append(missing, pt)
		}
	}
	return missing
}