package main

import (
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"os"

	"github.com/notnil/chess"
	"golang.org/x/image/bmp"
)

func renderBMP(cfg Config, data GameData) {
	img := image.NewRGBA(image.Rect(0, 0, ImgW, ImgH))
	draw.Draw(img, img.Bounds(), &image.Uniform{cfg.BoardBg}, image.Point{}, draw.Src)

	x0 := (ImgW - BoardSize) / 2
	y0 := 20

	// Center the board vertically in portrait mode
	if cfg.Portrait {
		y0 = (ImgH - BoardSize) / 2
	}

	cellSize := BoardSize / 8

	if cfg.BorderWidth > 0 {
		fillRect(img, x0-cfg.BorderWidth, y0-cfg.BorderWidth, BoardSize+cfg.BorderWidth*2, BoardSize+cfg.BorderWidth*2, cfg.BorderColor)
	}

	for r := 0; r < 8; r++ {
		for c := 0; c < 8; c++ {
			clr := cfg.LightSquare
			if (r+c)%2 == 1 {
				clr = cfg.DarkSquare
			}
			fillRect(img, x0+c*cellSize, y0+r*cellSize, cellSize, cellSize, clr)
		}
	}

	if cfg.HighlightLast && data.LastMove != nil {
		sRank := 7 - int(data.LastMove.S1().Rank())
		sFile := int(data.LastMove.S1().File())
		dRank := 7 - int(data.LastMove.S2().Rank())
		dFile := int(data.LastMove.S2().File())

		fillHighlight(img, x0+sFile*cellSize, y0+sRank*cellSize, cellSize, cfg.HighlightColor)
		fillHighlight(img, x0+dFile*cellSize, y0+dRank*cellSize, cellSize, cfg.HighlightColor)
	}

	if cfg.GridWidth > 0 {
		for i := 0; i <= 8; i++ {
			fillRect(img, x0, y0+i*cellSize, BoardSize, cfg.GridWidth, cfg.GridColor)
			fillRect(img, x0+i*cellSize, y0, cfg.GridWidth, BoardSize, cfg.GridColor)
		}
	}

	board := data.Pos.Board()
	for sq := chess.A1; sq <= chess.H8; sq++ {
		p := board.Piece(sq)
		if p == chess.NoPiece {
			continue
		}
		file := int(sq.File())
		rank := 7 - int(sq.Rank())
		cx := x0 + file*cellSize + cellSize/2
		cy := y0 + rank*cellSize + cellSize/2

		isWhite := p.Color() == chess.White
		col := cfg.WhitePieceColor
		if !isWhite {
			col = cfg.BlackPieceColor
		}
		drawPiece(img, cx, cy, cellSize, p.Type(), isWhite, col, cfg.PieceStyle, cfg.SvgDir)
	}

	if cfg.ShowCoords {
		for i := 0; i < 8; i++ {
			letter := string(rune('a' + i))
			drawText(img, x0+i*cellSize+cellSize/2, y0+BoardSize+15, letter, cfg.GridColor, 12, "center")
			num := fmt.Sprintf("%d", 8-i)
			drawText(img, x0-15, y0+i*cellSize+cellSize/2, num, cfg.GridColor, 12, "center")
		}
	}

	// Layout Fork: Portrait vs Landscape
	if cfg.Portrait {
		// --- TOP AREA: Black Player Info & Captures ---
		if cfg.ShowPlayers {
			drawText(img, ImgW/2, 60, fmt.Sprintf("B: %s", data.Black), AllowedPalette["black"], 18, "center")
		}
		drawCaptured(img, x0, 80, BoardSize, data.CapturedWhite, true, cfg.WhitePieceColor, cfg.PieceStyle, cfg.SvgDir)

		// --- BOTTOM AREA: White Player Info, Captures, & Game Stats ---
		bottomStartY := y0 + BoardSize

		if cfg.ShowPlayers {
			drawText(img, ImgW/2, bottomStartY+40, fmt.Sprintf("W: %s", data.White), AllowedPalette["black"], 18, "center")
		}
		drawCaptured(img, x0, bottomStartY+60, BoardSize, data.CapturedBlack, false, cfg.BlackPieceColor, cfg.PieceStyle, cfg.SvgDir)

		if cfg.ShowMoveText && data.LastMove != nil {
			dots := "."
			if data.Pos.Turn() == chess.White {
				dots = "..."
			}
			moveTxt := fmt.Sprintf("Move %d: %d%s %s", data.MoveNumber, data.MoveNumber, dots, data.SAN)
			drawText(img, ImgW/2, bottomStartY+130, moveTxt, cfg.MoveTextColor, 20, "center")
		}

		if cfg.ShowResult && data.Result != "" && data.Result != "*" {
			resTxt := fmt.Sprintf("Result: %s", data.Result)
			drawText(img, ImgW/2, bottomStartY+165, resTxt, AllowedPalette["red"], 18, "center")
		}

	} else {
		// --- LANDSCAPE AREA ---
		drawCaptured(img, 20, y0, 160, data.CapturedWhite, true, cfg.WhitePieceColor, cfg.PieceStyle, cfg.SvgDir)
		drawCaptured(img, ImgW-180, y0, 160, data.CapturedBlack, false, cfg.BlackPieceColor, cfg.PieceStyle, cfg.SvgDir)

		statusY := y0 + BoardSize + 30
		if cfg.ShowPlayers {
			leftText := fmt.Sprintf("W: %s", data.White)
			drawText(img, 20, statusY, leftText, AllowedPalette["black"], 16, "left")
			rightText := fmt.Sprintf("B: %s", data.Black)
			drawText(img, ImgW-20, statusY, rightText, AllowedPalette["black"], 16, "right")
		}

		if cfg.ShowMoveText && data.LastMove != nil {
			dots := "."
			if data.Pos.Turn() == chess.White {
				dots = "..."
			}
			moveTxt := fmt.Sprintf("Move %d: %d%s %s", data.MoveNumber, data.MoveNumber, dots, data.SAN)
			drawText(img, ImgW/2, statusY, moveTxt, cfg.MoveTextColor, 20, "center")
		}

		if cfg.ShowResult && data.Result != "" && data.Result != "*" {
			resTxt := fmt.Sprintf("Result: %s", data.Result)
			drawText(img, ImgW/2, statusY+25, resTxt, AllowedPalette["red"], 18, "center")
		}
	}

	out, err := os.Create(cfg.Output)
	if err != nil {
		panic(err)
	}
	defer out.Close()
	if err := bmp.Encode(out, img); err != nil {
		panic(err)
	}
}

func fillRect(img *image.RGBA, x, y, w, h int, c color.RGBA) {
	for yy := y; yy < y+h; yy++ {
		for xx := x; xx < x+w; xx++ {
			if xx >= 0 && xx < ImgW && yy >= 0 && yy < ImgH {
				img.Set(xx, yy, c)
			}
		}
	}
}

func fillHighlight(img *image.RGBA, x, y, size int, c color.RGBA) {
	for yy := y; yy < y+size; yy++ {
		for xx := x; xx < x+size; xx++ {
			if xx >= 0 && xx < ImgW && yy >= 0 && yy < ImgH {
				bg := img.RGBAAt(xx, yy)
				nr := uint8((uint16(bg.R) + uint16(c.R)) / 2)
				ng := uint8((uint16(bg.G) + uint16(c.G)) / 2)
				nb := uint8((uint16(bg.B) + uint16(c.B)) / 2)
				img.SetRGBA(xx, yy, color.RGBA{nr, ng, nb, 255})
			}
		}
	}
}