package main

import (
    "flag"
    "fmt"
    "image"
    "image/color"
    "log"
    "os"
    "strings"

    "golang.org/x/image/bmp"
)

const boardSize = 19
const imgW = 800
const imgH = 480

var palette = map[string]color.RGBA{
    "white":  {255, 255, 255, 255},
    "black":  {0, 0, 0, 255},
    "red":    {255, 0, 0, 255},
    "yellow": {255, 255, 0, 255},
    "blue":   {0, 0, 255, 255},
    "green":  {0, 255, 0, 255},
}

type Stone int

const (
    Empty Stone = iota
    Black
    White
)

func (s Stone) String() string {
    switch s {
    case Black:
        return "B"
    case White:
        return "W"
    default:
        return "."
    }
}

type Move struct {
    Color Stone
    X, Y  int
}

type Board struct {
    Grid          [boardSize][boardSize]Stone
    CapturedBlack int // number of black stones captured
    CapturedWhite int // number of white stones captured
}

var debug bool

////////////////////////////////////////////////////////////////////////////////

func main() {
    input := flag.String("input", "", "SGF file")
    moveNum := flag.Int("move", 0, "Move number")
    output := flag.String("output", "frame.bmp", "Output")

    bgColor := flag.String("bg", "white", "white|black")
    boardColor := flag.String("board", "yellow", "yellow|white")
    whiteColor := flag.String("white-color", "red", "white|green|blue|red")
    blackColor := flag.String("black-color", "black", "black|red")

    gridThickness := flag.Int("grid-thickness", 1, "1 or 2")
    highlightMode := flag.String("highlight", "ring", "dot|ring|none")

    flag.BoolVar(&debug, "debug", false, "print diagnostic output")

    flag.Parse()

    if *input == "" {
        log.Fatal("ERROR: -input is required")
    }

    validateColor("bg", *bgColor)
    validateColor("board", *boardColor)
    validateColor("white-color", *whiteColor)
    validateColor("black-color", *blackColor)

    diag("Input SGF: %s", *input)
    diag("Output BMP: %s", *output)
    diag("Requested move: %d", *moveNum)

    data, err := os.ReadFile(*input)
    if err != nil {
        log.Fatalf("ERROR: could not read SGF file %q: %v", *input, err)
    }

    diag("Read %d bytes from SGF", len(data))

    moves := parseSGF(string(data))

    diag("Parsed %d moves", len(moves))

    for i := 0; i < len(moves) && i < 10; i++ {
        diag(
            "Move %3d: %s at SGF(%c%c) board(%d,%d)",
            i+1,
            moves[i].Color,
            byte('a'+moves[i].X),
            byte('a'+moves[i].Y),
            moves[i].X,
            moves[i].Y,
        )
    }

    if len(moves) == 0 {
        diag("WARNING: no moves were parsed. Board will contain no stones.")
    }

    if *moveNum > len(moves) {
        diag("WARNING: requested move %d but SGF only has %d moves", *moveNum, len(moves))
    }

    board := Board{}

    applied := 0
    for i := 0; i < *moveNum && i < len(moves); i++ {
        diag("Applying move %d/%d: %s (%d,%d)", i+1, *moveNum, moves[i].Color, moves[i].X, moves[i].Y)
        board.Play(moves[i])
        applied++
    }

    blackOnBoard, whiteOnBoard := board.CountStones()

    diag("Applied moves: %d", applied)
    diag("Black stones on board: %d", blackOnBoard)
    diag("White stones on board: %d", whiteOnBoard)
    diag("Captured black stones: %d", board.CapturedBlack)
    diag("Captured white stones: %d", board.CapturedWhite)

    img := render(
        board,
        moves,
        *moveNum,
        *gridThickness,
        *bgColor,
        *boardColor,
        *whiteColor,
        *blackColor,
        *highlightMode,
    )

    f, err := os.Create(*output)
    if err != nil {
        log.Fatalf("ERROR: could not create output file %q: %v", *output, err)
    }
    defer f.Close()

    if err := bmp.Encode(f, img); err != nil {
        log.Fatalf("ERROR: could not encode BMP %q: %v", *output, err)
    }

    diag("Wrote BMP successfully: %s", *output)
}

func diag(format string, args ...any) {
    if debug {
        log.Printf(format, args...)
    }
}

func validateColor(flagName, name string) {
    if _, ok := palette[name]; !ok {
        log.Fatalf("ERROR: unknown color for -%s: %q", flagName, name)
    }
}

////////////////////////////////////////////////////////////////////////////////
// SGF

func parseSGF(s string) []Move {
    var moves []Move

    s = strings.ReplaceAll(s, "\n", "")
    s = strings.ReplaceAll(s, "\r", "")
    s = strings.ReplaceAll(s, "\t", "")

    tokens := strings.Split(s, ";")

    diag("SGF split into %d semicolon tokens", len(tokens))

    malformed := 0

    for _, t := range tokens {
        t = strings.TrimSpace(t)

        if !(strings.HasPrefix(t, "B[") || strings.HasPrefix(t, "W[")) {
            continue
        }

        end := strings.Index(t, "]")
        if end < 0 {
            malformed++
            diag("Malformed move token, missing closing bracket: %q", t)
            continue
        }

        coord := t[2:end]

        // SGF pass move: B[] or W[]
        if coord == "" {
            diag("Pass move encountered and ignored: %q", t)
            continue
        }

        if len(coord) < 2 {
            malformed++
            diag("Malformed move coordinate: %q from token %q", coord, t)
            continue
        }

        col := Black
        if t[0] == 'W' {
            col = White
        }

        x := int(coord[0] - 'a')
        y := int(coord[1] - 'a')

        if !inBounds(x, y) {
            malformed++
            diag("Out-of-bounds move ignored: %q -> (%d,%d)", coord, x, y)
            continue
        }

        moves = append(moves, Move{col, x, y})
    }

    diag("Malformed/out-of-bounds move tokens ignored: %d", malformed)

    return moves
}

////////////////////////////////////////////////////////////////////////////////
// RULES

func (b *Board) Play(m Move) {
    if !inBounds(m.X, m.Y) {
        diag("Ignoring out-of-bounds move: %s (%d,%d)", m.Color, m.X, m.Y)
        return
    }

    if b.Grid[m.Y][m.X] != Empty {
        diag(
            "WARNING: overwriting occupied point at (%d,%d): old=%s new=%s",
            m.X,
            m.Y,
            b.Grid[m.Y][m.X],
            m.Color,
        )
    }

    b.Grid[m.Y][m.X] = m.Color

    enemy := Black
    if m.Color == Black {
        enemy = White
    }

    for _, d := range [][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}} {
        nx, ny := m.X+d[0], m.Y+d[1]

        if inBounds(nx, ny) && b.Grid[ny][nx] == enemy {
            if !b.hasLiberty(nx, ny, make(map[[2]int]bool)) {
                beforeBlack := b.CapturedBlack
                beforeWhite := b.CapturedWhite

                b.removeGroup(nx, ny)

                diag(
                    "Capture after move %s (%d,%d): captured black +%d, white +%d",
                    m.Color,
                    m.X,
                    m.Y,
                    b.CapturedBlack-beforeBlack,
                    b.CapturedWhite-beforeWhite,
                )
            }
        }
    }

    // This does not enforce suicide as illegal, but warns if it happens.
    if b.Grid[m.Y][m.X] == m.Color && !b.hasLiberty(m.X, m.Y, make(map[[2]int]bool)) {
        diag("WARNING: move %s at (%d,%d) leaves own group without liberties", m.Color, m.X, m.Y)
    }
}

func (b *Board) hasLiberty(x, y int, visited map[[2]int]bool) bool {
    key := [2]int{x, y}
    if visited[key] {
        return false
    }
    visited[key] = true

    color := b.Grid[y][x]

    for _, d := range [][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}} {
        nx, ny := x+d[0], y+d[1]

        if !inBounds(nx, ny) {
            continue
        }

        if b.Grid[ny][nx] == Empty {
            return true
        }

        if b.Grid[ny][nx] == color {
            if b.hasLiberty(nx, ny, visited) {
                return true
            }
        }
    }

    return false
}

func (b *Board) removeGroup(x, y int) {
    color := b.Grid[y][x]
    stack := [][2]int{{x, y}}
    count := 0

    for len(stack) > 0 {
        p := stack[len(stack)-1]
        stack = stack[:len(stack)-1]

        px, py := p[0], p[1]

        if !inBounds(px, py) || b.Grid[py][px] != color {
            continue
        }

        b.Grid[py][px] = Empty
        count++

        for _, d := range [][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}} {
            stack = append(stack, [2]int{px + d[0], py + d[1]})
        }
    }

    // Correct capture counter logic:
    // If black stones were removed, black stones were captured.
    // If white stones were removed, white stones were captured.
    if color == Black {
        b.CapturedBlack += count
    } else if color == White {
        b.CapturedWhite += count
    }

    diag("Removed group: color=%s count=%d", color, count)
}

func (b *Board) CountStones() (black, white int) {
    for y := 0; y < boardSize; y++ {
        for x := 0; x < boardSize; x++ {
            switch b.Grid[y][x] {
            case Black:
                black++
            case White:
                white++
            }
        }
    }
    return black, white
}

func inBounds(x, y int) bool {
    return x >= 0 && y >= 0 && x < boardSize && y < boardSize
}

////////////////////////////////////////////////////////////////////////////////
// RENDER

func render(
    board Board,
    moves []Move,
    moveNum int,
    gridThickness int,
    bgName, boardName, whiteName, blackName string,
    highlightMode string,
) *image.RGBA {
    img := image.NewRGBA(image.Rect(0, 0, imgW, imgH))

    bg := palette[bgName]
    boardCol := palette[boardName]
    whiteCol := palette[whiteName]
    blackCol := palette[blackName]

    fill(img, bg)

    margin := 20
    targetBoardPx := imgH - 2*margin
    cell := targetBoardPx / (boardSize - 1)
    boardPx := cell * (boardSize - 1)

    offsetX := (imgW - boardPx) / 2
    offsetY := margin

    diag("Render geometry:")
    diag("  imgW=%d imgH=%d", imgW, imgH)
    diag("  margin=%d", margin)
    diag("  cell=%d", cell)
    diag("  boardPx=%d", boardPx)
    diag("  offsetX=%d offsetY=%d", offsetX, offsetY)

    fillRect(img, offsetX, offsetY, boardPx, boardPx, boardCol)

    gridCol := palette["black"]

    for i := 0; i < boardSize; i++ {
        x := offsetX + i*cell
        y := offsetY + i*cell

        drawLine(img, x, offsetY, x, offsetY+boardPx, gridCol, gridThickness)
        drawLine(img, offsetX, y, offsetX+boardPx, y, gridCol, gridThickness)
    }

    r := cell/2 - 3

    diag("Stone radius=%d", r)

    // Draw board stones.
    for y := 0; y < boardSize; y++ {
        for x := 0; x < boardSize; x++ {
            cx := offsetX + x*cell
            cy := offsetY + y*cell

            switch board.Grid[y][x] {
            case Black:
                circle(img, cx, cy, r, blackCol)
            case White:
                circle(img, cx, cy, r, whiteCol)
                circleOutline(img, cx, cy, r, palette["black"])
            }
        }
    }

    // Highlight last played move.
    if highlightMode != "none" && moveNum > 0 && moveNum <= len(moves) {
        m := moves[moveNum-1]
        cx := offsetX + m.X*cell
        cy := offsetY + m.Y*cell

        diag(
            "Highlighting move %d: %s at board(%d,%d), pixel(%d,%d)",
            moveNum,
            m.Color,
            m.X,
            m.Y,
            cx,
            cy,
        )

        if highlightMode == "dot" {
            circle(img, cx, cy, cell/6, palette["red"])
        } else {
            circleOutline(img, cx, cy, cell/2-1, palette["red"])
        }
    } else {
        diag(
            "No highlight drawn: mode=%q moveNum=%d len(moves)=%d",
            highlightMode,
            moveNum,
            len(moves),
        )
    }

    drawCaptureGrids(img, board, offsetX, offsetY, boardPx, r, whiteCol, blackCol)

    return img
}
func drawCaptureGrids(
    img *image.RGBA,
    b Board,
    offsetX, offsetY, boardPx, r int,
    whiteCol, blackCol color.RGBA,
) {
    stoneDiameter := 2 * r
    spacing := stoneDiameter + 4

    // Extra whitespace between the main board and captured-stone areas.
    captureGap := 24

    // ---------- LEFT AREA ----------
    leftWidth := offsetX - captureGap - r - 6
    if leftWidth > spacing {
        cols := leftWidth / spacing
        rows := boardPx / spacing

        capacity := cols * rows
        count := b.CapturedWhite
        if count > capacity {
            count = capacity
        }

        for i := 0; i < count; i++ {
            col := i / rows
            row := i % rows

            x := offsetX - captureGap - r - col*spacing
            y := offsetY + r + row*spacing

            circle(img, x, y, r, whiteCol)
            circleOutline(img, x, y, r, palette["black"])
        }

        diag(
            "Captured white: %d shown of %d (capacity=%d)",
            count,
            b.CapturedWhite,
            capacity,
        )
    }

    // ---------- RIGHT AREA ----------
    rightStart := offsetX + boardPx
    rightWidth := imgW - rightStart - captureGap - r - 6

    if rightWidth > spacing {
        cols := rightWidth / spacing
        rows := boardPx / spacing

        capacity := cols * rows
        count := b.CapturedBlack
        if count > capacity {
            count = capacity
        }

        for i := 0; i < count; i++ {
            col := i / rows
            row := i % rows

            x := rightStart + captureGap + r + col*spacing
            y := offsetY + r + row*spacing

            circle(img, x, y, r, blackCol)
        }

        diag(
            "Captured black: %d shown of %d (capacity=%d)",
            count,
            b.CapturedBlack,
            capacity,
        )
    }
}
////////////////////////////////////////////////////////////////////////////////
// DRAW

func fill(img *image.RGBA, c color.RGBA) {
    for y := 0; y < imgH; y++ {
        for x := 0; x < imgW; x++ {
            safeSet(img, x, y, c)
        }
    }
}

func fillRect(img *image.RGBA, x, y, w, h int, c color.RGBA) {
    for yy := y; yy < y+h; yy++ {
        for xx := x; xx < x+w; xx++ {
            safeSet(img, xx, yy, c)
        }
    }
}

func drawLine(img *image.RGBA, x0, y0, x1, y1 int, c color.RGBA, t int) {
    if t < 1 {
        t = 1
    }

    for d := -t / 2; d <= t/2; d++ {
        if x0 == x1 {
            for y := y0; y <= y1; y++ {
                safeSet(img, x0+d, y, c)
            }
        } else {
            for x := x0; x <= x1; x++ {
                safeSet(img, x, y0+d, c)
            }
        }
    }
}

func circle(img *image.RGBA, cx, cy, r int, col color.RGBA) {
    if r <= 0 {
        return
    }

    for dy := -r; dy <= r; dy++ {
        for dx := -r; dx <= r; dx++ {
            if dx*dx+dy*dy <= r*r {
                safeSet(img, cx+dx, cy+dy, col)
            }
        }
    }
}

func circleOutline(img *image.RGBA, cx, cy, r int, col color.RGBA) {
    if r <= 1 {
        return
    }

    for dy := -r; dy <= r; dy++ {
        for dx := -r; dx <= r; dx++ {
            d2 := dx*dx + dy*dy
            if d2 <= r*r && d2 >= (r-1)*(r-1) {
                safeSet(img, cx+dx, cy+dy, col)
            }
        }
    }
}

func safeSet(img *image.RGBA, x, y int, c color.RGBA) {
    if x < 0 || y < 0 || x >= imgW || y >= imgH {
        return
    }

    img.Set(x, y, c)
}

////////////////////////////////////////////////////////////////////////////////
// OPTIONAL BOARD DUMP

func dumpBoard(b Board) {
    if !debug {
        return
    }

    for y := 0; y < boardSize; y++ {
        var row strings.Builder

        for x := 0; x < boardSize; x++ {
            row.WriteString(fmt.Sprintf("%s ", b.Grid[y][x]))
        }

        log.Print(row.String())
    }
}
