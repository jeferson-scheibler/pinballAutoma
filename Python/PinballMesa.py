import cv2
import time 
import numpy
import serial

prev_frame_time = 0
new_frame_time = 0
kernel = numpy.ones((5 ,5), numpy.uint8)


captura = cv2.VideoCapture(1)

arduino = serial.Serial('COM5', 115200)

posX = []
posY = []

predictedPosX = 0
predictedPosY = 0


class hitBox:
    x = 0
    y = 0
    x2 = 0
    y2 = 0
    w = 0
    h = 0

class lancadorBase:
    x = 0
    y = 0
    x2 = 0
    y2 = 0
    w = 0
    h = 0

hb = hitBox()
lb = lancadorBase()

delaylancamento = False


#Pega 1 frame da camera
def getImage():
    global captura
    ret, frame = captura.read()
    frame = cv2.resize(frame, (800, 600)) 
    return frame

#Faz o calculo de frames /s e retorna o valor numerico
def calcFrame():
    global prev_frame_time
    global new_frame_time
    new_frame_time = time.time() 
    fps = 1/(new_frame_time-prev_frame_time) 
    prev_frame_time = new_frame_time 
    fps = int(fps) 
    fps = str(fps) 
    return fps


def drawRoute(image):
    global posX
    global posY
    x = 0
    num_elementos_lista = len(posX)
    while(x < num_elementos_lista):
        xL = int(posX[x])
        yL = int(posY[x])
        cv2.rectangle(image,(xL,yL), (xL+2,yL+2), (0,255,0), 3)
        x +=1
    
def detectCircle(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) 
    gray_blurred = cv2.blur(gray, (3, 3)) 
    detected_circles = cv2.HoughCircles(gray_blurred,  
                       cv2.HOUGH_GRADIENT, 1, 20, param1 = 100, 
                   param2 = 30, minRadius = 13, maxRadius = 20) 
    if detected_circles is not None: 
        detected_circles = numpy.uint16(numpy.around(detected_circles)) 
      
        for pt in detected_circles[0, :]: 
            a, b, r = int(pt[0]), int(pt[1]), int(pt[2])  # int nativo: evita overflow de uint16 no NumPy 2.x
            cv2.circle(image, (a, b), r, (0, 255, 0), 2) 
            cv2.circle(image, (a, b), 1, (0, 0, 255), 3)
            return a,b,r 
    else:
        return 0, 0, 0
    
def predictnextPos(image):
    global posX
    global posY
    global predictedPosX
    global predictedPosY
    try:
        x1 = int(posX[0])
        y1 = int(posY[0])
        
        x2 = int(posX[1])
        y2 = int(posY[1])
        
        valx = x1-x2
        valy = y1-y2
        
        newPosx = (valx*1)+posX[0]
        newPosy = (valy*1)+posY[0]
        
        predictedPosX = newPosx
        predictedPosY = newPosy
        
        cv2.circle(image, (newPosx, newPosy), 5, (0, 0,255 ), 3)
    except:
       pass
       
def findBase(image):
    global hb
    rangomax = numpy.array([60, 60, 255]) # B, G, R
    rangomin = numpy.array([0, 0, 100])
    mask = cv2.inRange(image, rangomin, rangomax)
    # reduce the noise
    opening = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    x, y, w, h = cv2.boundingRect(opening)
    
    hb.x = x-70
    hb.y = y
    hb.x2 = x+w+70
    hb.y2 = y+h+70
    hb.w = w+70
    hb.h = h+70
    
    
    t = hb.x2-hb.x
    t = t/2
    meio = hb.x+t
    
    cv2.rectangle(image, (int(meio), hb.y), (int(meio), hb.y2), (0, 255, 0), 1)
    cv2.rectangle(image, (hb.x, hb.y), (hb.x2, hb.y2), (0, 255, 0), 1)
    
    return image

def findLancador(image):
    global lb
    rangomax = numpy.array([255, 60, 60]) # B, G, R
    rangomin = numpy.array([60, 0, 0])
    mask = cv2.inRange(image, rangomin, rangomax)
    # reduce the noise
    opening = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    x, y, w, h = cv2.boundingRect(opening)
    
    lb.x = x+15
    lb.y = y
    lb.x2 = x+w+40
    lb.y2 = y+h+30
    lb.w = w+40
    lb.h = h+30
    
    cv2.rectangle(image, (lb.x, lb.y), (lb.x2, lb.y2), (0, 255, 0), 1)
    
    return image
    
def hit():
    global predictedPosX
    global predictedPosY
    try:
        xB = predictedPosX
        yB = predictedPosY
        if(xB > hb.x and yB > hb.y and xB < hb.x2 and yB < hb.y2):
            t = hb.x2-hb.x
            t = t/2
            meio = hb.x+t
            if xB > meio:
                print("Direito")
                arduino.write('2'.encode())
                posX[0] = 0
                posY[0] = 0
                return 0
            if xB < meio:
                print("Esquerdo")
                arduino.write('1'.encode())
                posX[0] = 0
                posY[0] = 0
                return 1
    except:
        pass
    
def lancar():
    global lb
    try:
        xB = predictedPosX
        yB = predictedPosY
        if(xB > lb.x and yB > lb.y and xB < lb.x2 and yB < lb.y2):
            print("Lancar")
            arduino.write('3'.encode())
            posX[0] = 0
            posY[0] = 0
            return 0
    except:
        pass

while(True):
    image = getImage()
    fps = calcFrame()
    font = cv2.FONT_HERSHEY_SIMPLEX
    x, y, r = detectCircle(image)
    
    
    if(r > 12):
        if(len(posX) >= 10):
            del(posX[9])
            del(posY[9])
        posX.insert(0,x)
        posY.insert(0,y)
        cv2.circle(image, (x, y), r, (0, 255, 0), 2)
    
    
    
    findBase(image)
    #findLancador(image)
    drawRoute(image)
    predictnextPos(image)
    result = hit()
    lancar()
    
    if result==0:
        cv2.putText(image, 'Direito', (0, 70), font, 1, (100, 255, 0), 2, cv2.LINE_AA)
    if result==1:
        cv2.putText(image, 'Esquerdo', (0, 70), font, 1, (100, 255, 0), 2, cv2.LINE_AA)
    
    
    cv2.putText(image, fps, (0, 45), font, 2, (100, 255, 0), 2, cv2.LINE_AA)
    cv2.imshow("Video", image)
    
    k = cv2.waitKey(1) & 0xff
    if k == 27:
        break


captura.release()
cv2.destroyAllWindows()
arduino.close()