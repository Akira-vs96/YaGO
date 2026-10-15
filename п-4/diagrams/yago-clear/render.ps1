$ErrorActionPreference='Stop'
$helpers=[IO.File]::ReadAllText((Join-Path $PSScriptRoot '../render-dfd.ps1'))
$helpers=$helpers.Substring(0,$helpers.IndexOf("StartSheet 1600 1050"))
. ([scriptblock]::Create($helpers))
$script:out=$PSScriptRoot
$script:pages=[Collections.Generic.List[string]]::new()
function Esc([string]$s){([Security.SecurityElement]::Escape($s)).Replace("`n",'&#xa;')}
function BeginPage([string]$name,[int]$height){
    StartSheet 1600 $height $name
    $script:pageName=$name
    $script:height=$height
    $script:cells=[Collections.Generic.List[string]]::new()
    $script:cells.Add('<mxCell id="0"/><mxCell id="1" parent="0"/>')
}
function Label([string]$id,[int]$x,[int]$y,[int]$w,[string]$text,[int]$size=20){
    Txt $x ($y+$size) $text $size '#23364D' 'start'
    $script:cells.Add(('<mxCell id="{0}" parent="1" vertex="1" value="{1}" style="text;html=0;align=left;verticalAlign=middle;fontFamily=Arial;fontSize={6};"><mxGeometry x="{2}" y="{3}" width="{4}" height="{5}" as="geometry"/></mxCell>' -f $id,(Esc $text),$x,$y,$w,($size+12),$size))
}
function Node([string]$id,[int]$x,[int]$y,[int]$w,[int]$h,[string[]]$lines,[string]$kind='external'){
    $fill='#F3F6FA';$round=0;$style='rounded=0;'
    if($kind -eq 'process'){$fill='#EAF7F6';$round=18;$style='rounded=1;arcSize=12;'}
    if($kind -eq 'store'){$fill='#F2F0FF';$style='shape=partialRectangle;right=0;'}
    if($kind -eq 'store'){
        Segment $x $y ($x+$w) $y
        Segment $x ($y+$h) ($x+$w) ($y+$h)
        Segment $x $y $x ($y+$h)
    }else{Box $x $y $w $h $fill '#23364D' $round}
    for($i=0;$i -lt $lines.Count;$i++){Txt ($x+$w/2) ($y+$h/2-($lines.Count-1)*14+8+$i*28) $lines[$i] 20}
    $v=Esc ($lines -join "`n")
    $script:cells.Add(('<mxCell id="{0}" parent="1" vertex="1" value="{1}" style="{6}whiteSpace=wrap;html=0;fillColor={7};strokeColor=#23364D;strokeWidth=2;fontSize=20;fontFamily=Arial;align=center;verticalAlign=middle;"><mxGeometry x="{2}" y="{3}" width="{4}" height="{5}" as="geometry"/></mxCell>' -f $id,$v,$x,$y,$w,$h,$style,$fill))
}
function Flow([string]$id,[string]$source,[string]$target,[int]$x1,[int]$x2,[int]$y,[string]$text,[double]$exitY,[double]$entryY){
    Arrow $x1 $x2 $y $text 17
    $script:cells.Add(('<mxCell id="{0}" parent="1" edge="1" source="{1}" target="{2}" value="{3}" style="edgeStyle=none;html=0;endArrow=block;endFill=1;strokeColor=#087F8C;strokeWidth=2;fontSize=17;fontFamily=Arial;labelBackgroundColor=#ffffff;verticalAlign=bottom;exitX=1;exitY={4};entryX=0;entryY={5};exitPerimeter=0;entryPerimeter=0;"><mxGeometry relative="1" as="geometry"><mxPoint x="0" y="-12" as="offset"/></mxGeometry></mxCell>' -f $id,$source,$target,(Esc $text),$exitY.ToString([Globalization.CultureInfo]::InvariantCulture),$entryY.ToString([Globalization.CultureInfo]::InvariantCulture)))
}
function Finish([string]$name){
    SaveSheet $name
    $script:pages.Add(('<diagram name="{0}" id="{1}"><mxGraphModel page="1" pageWidth="1600" pageHeight="{2}" grid="1" gridSize="10"><root>{3}</root></mxGraphModel></diagram>' -f (Esc $script:pageName),$name,$script:height,($script:cells -join "`n")))
}
# Each row is: participant label, data label, node kind.
$items=@(
    @{n=1; title='Пайдаланушыны тексеру'; brief='Кім кірді және қандай құқығы бар?';
      inputs=@(@('E1|Клиент','Кіру деректері','external'),@('D1|Пайдаланушылар, сессиялар','Сессия және рөлдер','store'));
      outputs=@(@('2.0|Сұранымды қабылдау','Тексерілген сессия','process'),@('D1|Пайдаланушылар, сессиялар','Жаңа сессия','store'),@('E1|Клиент','Кіру нәтижесі / қате','external'))},
    @{n=2; title='Сұранымды қабылдау'; brief='Клиент қандай қызмет сұрады?';
      inputs=@(@('E1|Клиент','Қызмет, мекенжай, себет/QR','external'),@('1.0|Пайдаланушыны тексеру','Тексерілген сессия','process'),@('D2|Тарифтер, парк, геозоналар','Тариф пен шектеулер','store'));
      outputs=@(@('3.0|Бағыт пен ресурсты таңдау','Тексерілген тапсырыс','process'),@('E1|Клиент','Қабылдау / қате себебі','external'))},
    @{n=3; title='Бағыт пен ресурсты таңдау'; brief='Кім орындайды немесе қай техника беріледі?';
      inputs=@(@('2.0|Сұранымды қабылдау','Тексерілген тапсырыс','process'),@('D2|Тарифтер, парк, геозоналар','Тариф, бос ресурс','store'),@('E4|OSRM — маршрут сервисі','Бағыт, қашықтық, уақыт','external'));
      outputs=@(@('E4|OSRM — маршрут сервисі','Маршрут сұранымы','external'),@('4.0|Қызметті орындау','Тағайындалған тапсырыс','process'),@('D3|Тапсырыстар, жалдаулар','Тапсырыс / бронь','store'))},
    @{n=4; title='Қызметті орындау'; brief='Мәртебе мен техниканың жауабын бақылау';
      inputs=@(@('3.0|Бағыт пен ресурсты таңдау','Тағайындалған тапсырыс','process'),@('E2|Жүргізуші / курьер / оператор','Мәртебе, координаттар','external'),@('E5|Құлып эмуляторы','Құлып жауабы, телеметрия','external'),@('D3|Тапсырыстар, жалдаулар','Ағымдағы тапсырыс','store'));
      outputs=@(@('E2|Жүргізуші / курьер / оператор','Орындау тапсырмасы','external'),@('E5|Құлып эмуляторы','Ашу / жабу командасы','external'),@('D3|Тапсырыстар, жалдаулар','Жаңа мәртебе, орын','store'),@('5.0|Қызметті аяқтау','Аяқталу деректері, құн','process'))},
    @{n=5; title='Қызметті аяқтау'; brief='Нәтижені сақтау және клиентке көрсету';
      inputs=@(@('4.0|Қызметті орындау','Аяқталу деректері, құн','process'),@('D3|Тапсырыстар, жалдаулар','Тапсырыс мәртебесі','store'));
      outputs=@(@('D3|Тапсырыстар, жалдаулар','Соңғы мәртебе, құн','store'),@('D4|Оқиғалар, қызмет тарихы','Қорытынды жазба','store'),@('E1|Клиент','Нәтиже, есептелген құн','external'))},
    @{n=6; title='Тарифтер мен паркті басқару'; brief='Әкімші тарифтер мен техника деректерін өзгертеді';
      inputs=@(@('E3|Әкімші','Тариф / парк өзгерістері','external'),@('D2|Тарифтер, парк, геозоналар','Ағымдағы деректер','store'));
      outputs=@(@('D2|Тарифтер, парк, геозоналар','Жаңартылған деректер','store'),@('E3|Әкімші','Өзгерту нәтижесі','external'))}
)
BeginPage '00 — Жалпы шолу' 1030
Label 'title' 50 35 1500 'YaGo — жүйенің 6 негізгі процесі' 36
Label 'sub' 50 90 1500 'Жобалық модель · шолу картасы; толық деректер ағындары келесі беттерде' 22
foreach($p in $items){
    $col=($p.n-1)%2;$row=[math]::Floor(($p.n-1)/2);$x=50+$col*780;$y=170+$row*245
    Node ('p'+$p.n) $x $y 710 125 @(($p.n.ToString()+'.0'),$p.title) 'process'
    Label ('desc'+$p.n) ($x+10) ($y+144) 700 $p.brief 20
}
Label 'foot1' 50 930 1500 'E — сыртқы қатысушы / жүйе; D — деректер қоймасы; 1.0–6.0 — процестер.' 21
Label 'foot2' 50 970 1500 'Әр бетте: сол жақта — кіріс деректері, ортасында — процесс, оң жақта — шығыс деректері.' 21
Finish '00-overview'
foreach($p in $items){
    $rows=[math]::Max($p.inputs.Count,$p.outputs.Count);$ph=$rows*125;$height=$ph+410
    BeginPage ($p.n.ToString()+' — '+$p.title) $height
    Label 'title' 45 30 1500 ($p.n.ToString()+'.0  '+$p.title) 34
    Label 'subtitle' 45 85 1500 $p.brief 22
    Label 'incoming' 45 150 500 'КІРІС: қандай дерек келеді?' 20
    Label 'outgoing' 1185 150 400 'ШЫҒЫС: не жіберіледі?' 20
    $titleFirst=($p.title -split ' ' | Select-Object -First 2) -join ' '
    $titleRest=($p.title -split ' ' | Select-Object -Skip 2) -join ' '
    $mainLines=@(($p.n.ToString()+'.0'),$titleFirst)
    if($titleRest){$mainLines+=$titleRest}
    Node 'main' 650 205 320 $ph $mainLines 'process'
    for($i=0;$i -lt $p.inputs.Count;$i++){
        $a=$p.inputs[$i];$y=220+$i*125
        Node ('in'+$i) 45 $y 300 90 ($a[0] -split '\|') $a[2]
        Flow ('fi'+$i) ('in'+$i) 'main' 345 650 ($y+45) $a[1] 0.5 (($y+45-205)/$ph)
    }
    for($i=0;$i -lt $p.outputs.Count;$i++){
        $a=$p.outputs[$i];$y=220+$i*125
        Node ('out'+$i) 1255 $y 300 90 ($a[0] -split '\|') $a[2]
        Flow ('fo'+$i) 'main' ('out'+$i) 970 1255 ($y+45) $a[1] (($y+45-205)/$ph) 0.5
    }
    Label 'legend1' 45 ($height-145) 1500 'Бірдей E / D нөмірі — бір объект. Басқа процестермен байланыс олардың нөмірі арқылы көрсетілген.' 19
    Label 'legend2' 45 ($height-108) 1500 'Бұл — бір DFD моделінің бөліктері. Беттер орындалу уақытын немесе міндетті кезекті белгілемейді.' 19
    $note='Қоймаға бағытталған жебе — жазу; қоймадан шыққан жебе — оқу.'
    if($p.n -eq 3){$note='OSRM — маршрут қажет қызметтер үшін. Самокат жалдауына автомобиль маршруты міндетті емес.'}
    if($p.n -eq 4){$note='Құлып эмуляторы — самокат / велосипед үшін. Жүргізуші / курьер — такси / жеткізу үшін.'}
    if($p.n -eq 5){$note='Есептелген құн төлем жасалғанын немесе фискалдық чек берілгенін білдірмейді.'}
    Label 'note' 45 ($height-65) 1500 $note 19
    Finish ('0'+$p.n+'-process')
}
[IO.File]::WriteAllText((Join-Path $script:out 'yago-readable.drawio'),('<mxfile host="app.diagrams.net">'+($script:pages -join "`n")+'</mxfile>'),[Text.UTF8Encoding]::new($false))
$html='<!doctype html><html lang="kk"><meta charset="utf-8"><title>YaGo — DFD</title><style>body{font:18px Arial;margin:30px auto;max-width:1600px;background:#edf2f7;color:#23364d}nav{position:sticky;top:0;background:white;padding:18px;display:flex;gap:20px;flex-wrap:wrap}a{color:#087f8c}img{width:100%;height:auto;background:white}section{margin:30px 0}h1{padding:0 20px}</style><h1>YaGo — түсінікті DFD</h1><nav><a href="yago-readable.drawio">Draw.io файлы</a><a href="#overview">Шолу</a>'
foreach($p in $items){$html+='<a href="#p'+$p.n+'">'+$p.n+'.0</a>'}
$html+='</nav><section id="overview"><img src="00-overview.svg" alt="Жалпы шолу"></section>'
foreach($p in $items){$html+='<section id="p'+$p.n+'"><img src="0'+$p.n+'-process.svg" alt="'+$p.title+'"></section>'}
$html+='</html>'
[IO.File]::WriteAllText((Join-Path $script:out 'index.html'),$html,[Text.UTF8Encoding]::new($false))
