Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = 'Stop'
$script:out = $PSScriptRoot
$script:ink = '#23364D'
$script:teal = '#087F8C'
$script:svg = $null

function ColorOf([string]$s) { [System.Drawing.ColorTranslator]::FromHtml($s) }
function StartSheet([int]$w, [int]$h, [string]$title) {
    $script:svg = [System.Text.StringBuilder]::new()
    [void]$script:svg.AppendLine("<svg xmlns='http://www.w3.org/2000/svg' width='$w' height='$h' viewBox='0 0 $w $h' role='img'><title>$title</title><rect width='$w' height='$h' fill='white'/>")
    $script:bmp = [System.Drawing.Bitmap]::new($w,$h)
    $script:g = [System.Drawing.Graphics]::FromImage($script:bmp)
    $script:g.Clear([System.Drawing.Color]::White)
    $script:g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $script:g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
}
function Txt([double]$x,[double]$y,[string]$s,[int]$size=20,[string]$color='#23364D',[string]$align='middle',[bool]$bold=$false) {
    $weight = if($bold){'bold'}else{'normal'}
    $safe = [System.Security.SecurityElement]::Escape($s)
    [void]$script:svg.AppendLine("<text x='$x' y='$y' font-family='Arial, sans-serif' font-size='$size' font-weight='$weight' text-anchor='$align' fill='$color'>$safe</text>")
    $style = if($bold){[System.Drawing.FontStyle]::Bold}else{[System.Drawing.FontStyle]::Regular}
    $font = [System.Drawing.Font]::new('Arial',$size,$style,[System.Drawing.GraphicsUnit]::Pixel)
    $brush = [System.Drawing.SolidBrush]::new((ColorOf $color))
    $format = [System.Drawing.StringFormat]::new()
    $format.Alignment = switch($align){'start'{[System.Drawing.StringAlignment]::Near};'end'{[System.Drawing.StringAlignment]::Far};default{[System.Drawing.StringAlignment]::Center}}
    $script:g.DrawString($s,$font,$brush,[System.Drawing.PointF]::new($x,($y-$size)), $format)
    $font.Dispose(); $brush.Dispose(); $format.Dispose()
}
function Box([int]$x,[int]$y,[int]$w,[int]$h,[string]$fill='#F3F6FA',[string]$stroke='#23364D',[int]$round=0) {
    [void]$script:svg.AppendLine("<rect x='$x' y='$y' width='$w' height='$h' rx='$round' fill='$fill' stroke='$stroke' stroke-width='2'/>")
    $brush=[System.Drawing.SolidBrush]::new((ColorOf $fill)); $pen=[System.Drawing.Pen]::new((ColorOf $stroke),2)
    if($round -gt 0){
        $p=[System.Drawing.Drawing2D.GraphicsPath]::new(); $d=2*$round
        $p.AddArc($x,$y,$d,$d,180,90); $p.AddArc(($x+$w-$d),$y,$d,$d,270,90)
        $p.AddArc(($x+$w-$d),($y+$h-$d),$d,$d,0,90); $p.AddArc($x,($y+$h-$d),$d,$d,90,90); $p.CloseFigure()
        $script:g.FillPath($brush,$p); $script:g.DrawPath($pen,$p); $p.Dispose()
    }else{ $script:g.FillRectangle($brush,$x,$y,$w,$h); $script:g.DrawRectangle($pen,$x,$y,$w,$h) }
    $brush.Dispose(); $pen.Dispose()
}
function Segment([int]$x1,[int]$y1,[int]$x2,[int]$y2,[string]$color='#23364D') {
    [void]$script:svg.AppendLine("<line x1='$x1' y1='$y1' x2='$x2' y2='$y2' stroke='$color' stroke-width='2'/>")
    $pen=[System.Drawing.Pen]::new((ColorOf $color),2); $script:g.DrawLine($pen,$x1,$y1,$x2,$y2); $pen.Dispose()
}
function Arrow([int]$x1,[int]$x2,[int]$y,[string]$label,[int]$size=17) {
    Segment $x1 $y $x2 $y $script:teal
    $d = if($x2 -gt $x1){-10}else{10}
    Segment $x2 $y ($x2+$d) ($y-5) $script:teal
    Segment $x2 $y ($x2+$d) ($y+5) $script:teal
    Txt (($x1+$x2)/2) ($y-9) $label $size
}
function Entity([int]$x,[int]$y,[int]$w,[string[]]$lines,[int]$h=80) {
    Box $x $y $w $h
    $base=$y+$h/2-($lines.Count-1)*12+7
    for($i=0;$i -lt $lines.Count;$i++){Txt ($x+$w/2) ($base+$i*24) $lines[$i] 19}
}
function Store([int]$x,[int]$y,[string]$id,[string]$label) {
    # Open-ended data store: Gane-Sarson notation.
    Segment $x $y ($x+285) $y
    Segment $x ($y+62) ($x+285) ($y+62)
    Segment $x $y $x ($y+62)
    Segment ($x+47) $y ($x+47) ($y+62)
    Txt ($x+24) ($y+38) $id 18 '#23364D' 'middle' $true
    Txt ($x+165) ($y+38) $label 18
}
function SaveSheet([string]$name) {
    [void]$script:svg.AppendLine('</svg>')
    [System.IO.File]::WriteAllText((Join-Path $script:out ($name+'.svg')),$script:svg.ToString(),[System.Text.UTF8Encoding]::new($false))
    $script:bmp.Save((Join-Path $script:out ($name+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
    $script:g.Dispose(); $script:bmp.Dispose()
}

StartSheet 1600 1050 'YaGo — контекстная DFD модуля аренды'
Txt 65 70 'YaGo / П4 / НЕДЕЛЯ 3' 18 '#087F8C' 'start' $true
Txt 65 122 'Аренда самокатов и велосипедов' 38 '#23364D' 'start' $true
Txt 65 165 'Контекстная DFD · процесс 0.0 · проектная модель' 23 '#52647A' 'start'
Box 1080 240 455 640 '#EAF7F6' '#087F8C' 24
Txt 1307 463 '0.0' 26 '#087F8C' 'middle' $true
Txt 1307 517 'Управлять арендой' 30 '#23364D' 'middle' $true
Txt 1307 562 'Серверный модуль YaGo' 23
Txt 1307 612 'Проверки, бронь, команды замку,' 20
Txt 1307 644 'состояния и расчёт стоимости' 20
$context=@(
    @{y=240; label=@('E1','Клиентское приложение'); input='Поиск, бронь, QR, запрос завершения'; output='Техника, тариф, результат, сумма'},
    @{y=410; label=@('E2','Эмулятор техники'); input='Телеметрия, ответы замка'; output='Команды открыть / закрыть замок'},
    @{y=580; label=@('E3','Оператор парка'); input='Действие обслуживания, причина'; output='Состояние техники, результат операции'},
    @{y=750; label=@('E4','Общий контур YaGo'); input='Проверенная личность и роль'; output='Заказ аренды, статус и сумма'}
)
foreach($e in $context){Entity 65 $e.y 320 $e.label 130; Arrow 385 1080 ($e.y+40) $e.input 21; Arrow 1080 385 ($e.y+103) $e.output 21}
Txt 65 941 'Стрелки обозначают передаваемые данные. Авторизация — в общем контуре; техника — эмулятор.' 20 '#52647A' 'start'
Txt 65 980 'Состав процесса 0.0 раскрыт на DFD уровня 1. Хранилища данных на контекстной схеме не показываются.' 20 '#52647A' 'start'
SaveSheet 'dfd-context'

StartSheet 1600 2610 'YaGo — DFD уровня 1: пять процессов аренды'
$script:mermaid = [System.Collections.Generic.List[string]]::new()
$script:mermaid.Add('%% Generated by render-dfd.ps1. PNG/SVG use Gane-Sarson data-store notation.')
$script:mermaid.Add('flowchart LR')
Txt 45 60 'YaGo / П4 / НЕДЕЛЯ 3' 18 '#087F8C' 'start' $true
Txt 45 107 'Потоки данных модуля аренды' 36 '#23364D' 'start' $true
Txt 45 149 'DFD уровня 1 · декомпозиция процесса 0.0 · нотация Гейна—Сарсона' 21 '#52647A' 'start'
Txt 45 184 'E и D с одинаковым номером — повтор одного объекта. Полосы показывают процессы, а не шаги по времени.' 19 '#52647A' 'start'

function Panel([int]$n,[string]$title,[string[]]$body) {
    $script:processId = 'P'+$n
    $script:mermaid.Add(('    P{0}("{0}.0 {1}")' -f $n,$title))
    $script:base=230+($n-1)*455
    Segment 45 $script:base 1550 $script:base '#D4DFE8'
    Txt 45 ($script:base+33) ($n.ToString()+'.0  '+$title) 24 '#23364D' 'start' $true
    Box 630 ($script:base+60) 335 350 '#EAF7F6' '#087F8C' 20
    Txt 797 ($script:base+125) ($n.ToString()+'.0') 25 '#087F8C' 'middle' $true
    for($i=0;$i -lt $body.Count;$i++){Txt 797 ($script:base+205+$i*31) $body[$i] 22}
}
function ExternalRow([int]$slot,[string[]]$name,[string]$incoming,[string]$outgoing) {
    $eid = [regex]::Match($name[0],'^E\d').Value
    $script:mermaid.Add(('    {0}["{1}"]' -f $eid,$name[0]))
    if($incoming){$script:mermaid.Add(('    {0} -->|"{1}"| {2}' -f $eid,$incoming,$script:processId))}
    if($outgoing){$script:mermaid.Add(('    {0} -->|"{1}"| {2}' -f $script:processId,$outgoing,$eid))}
    $y=$script:base+65+$slot*87
    Entity 45 $y 255 $name 68
    if($incoming){Arrow 300 630 ($y+24) $incoming 16}
    if($outgoing){Arrow 630 300 ($y+61) $outgoing 16}
}
function DataRow([int]$slot,[string]$id,[string]$name,[string]$read,[string]$write) {
    $script:mermaid.Add(('    {0}[("{0} {1}")]' -f $id,$name))
    if($read){$script:mermaid.Add(('    {0} -->|"{1}"| {2}' -f $id,$read,$script:processId))}
    if($write){$script:mermaid.Add(('    {0} -->|"{1}"| {2}' -f $script:processId,$write,$id))}
    $y=$script:base+65+$slot*87
    Store 1260 $y $id $name
    if($read){Arrow 1260 965 ($y+24) $read 16}
    if($write){Arrow 965 1260 ($y+59) $write 16}
}
Panel 1 'Найти доступную технику' @('Отобрать технику','по области поиска','и условиям доступности')
ExternalRow 1 @('E1 · Клиент') 'Область поиска, фильтры' 'Техника, зоны, тарифы'
DataRow 0 'D2' 'Техника' 'Координаты и состояние' ''
DataRow 2 'D3' 'Тарифы и зоны' 'Тарифы, полигоны зон' ''

Panel 2 'Создать бронь' @('Проверить условия','и атомарно закрепить','технику за клиентом')
ExternalRow 0 @('E1 · Клиент') 'Техника, выбранный тариф' 'Бронь и срок / отказ'
ExternalRow 2 @('E4 · Общий контур') 'Личность и роль' 'Заказ аренды, статус'
DataRow 0 'D2' 'Техника' 'Состояние и телеметрия' 'Статус reserved'
DataRow 1 'D3' 'Тарифы и зоны' 'Активный тариф, зоны' ''
DataRow 2 'D4' 'Заказы и аренды' 'Незавершённые аренды' 'Бронь, заказ, снимок тарифа'
DataRow 3 'D5' 'Журнал операций' '' 'Результат проверки'

Panel 3 'Начать аренду по QR' @('Проверить бронь,','отправить команду,','обработать ответ замка')
ExternalRow 0 @('E1 · Клиент') 'QR-токен, номер брони' 'Результат запуска'
ExternalRow 1 @('E4 · Общий контур') 'Личность и роль' 'Статус заказа'
ExternalRow 3 @('E2 · Эмулятор') 'Ответ замка, ID команды' 'Команда открытия, ID'
DataRow 0 'D2' 'Техника' 'QR, состояние, телеметрия' 'Статус и состояние замка'
DataRow 1 'D4' 'Заказы и аренды' 'Владелец, срок, статус' 'Статус и время старта'
DataRow 3 'D5' 'Журнал операций' '' 'Команда, ответ, ошибка'

Panel 4 'Обработать поездку и завершение' @('Учесть телеметрию,','проверить парковку,','закрыть замок и','рассчитать стоимость')
ExternalRow 0 @('E1 · Клиент') 'Завершение, номер аренды' 'Статус, сумма / отказ'
ExternalRow 1 @('E4 · Общий контур') 'Личность и роль' 'Статус заказа и сумма'
ExternalRow 3 @('E2 · Эмулятор') 'Телеметрия, ответ замка' 'Команда закрытия, ID'
DataRow 0 'D2' 'Техника' 'Состояние и позиция' 'Телеметрия, статус'
DataRow 1 'D3' 'Тарифы и зоны' 'Активные геозоны' ''
DataRow 2 'D4' 'Заказы и аренды' 'Аренда, снимок тарифа' 'Статус, время, сумма'
DataRow 3 'D5' 'Журнал операций' '' 'Команда, ответ, решение'

Panel 5 'Обслужить парк' @('Проверить полномочия','и занятость техники,','сохранить результат')
ExternalRow 0 @('E3 · Оператор') 'Действие, техника, причина' 'Состояние, результат'
ExternalRow 2 @('E4 · Общий контур') 'Личность и роль' ''
DataRow 0 'D2' 'Техника' 'Состояние и телеметрия' 'Состояние обслуживания'
DataRow 1 'D4' 'Заказы и аренды' 'Связанная активная аренда' ''
DataRow 3 'D5' 'Журнал операций' '' 'Действие, причина, автор'
Txt 45 2538 'D2 — vehicles; D3 — tariffs + zones; D4 — orders + rentals; D5 — проектный журнал операций.' 19 '#52647A' 'start'
Txt 45 2575 'Начало и завершение поездки требуют ответа замка. При потере связи занятая техника не освобождается.' 19 '#52647A' 'start'
SaveSheet 'dfd-level-1'
[System.IO.File]::WriteAllLines((Join-Path $script:out 'scooter-dfd.mmd'),$script:mermaid,[System.Text.UTF8Encoding]::new($false))
