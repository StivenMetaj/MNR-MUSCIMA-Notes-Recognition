import matplotlib
import json

matplotlib.use("Agg")
from muscima.io import parse_cropobject_list
from tqdm import tqdm

import random
import cv2

from utils import *

''' seed for dataset conversion reproducibility  '''
seed = 0

''' size of patches: they will become patchesDim x patchesDim '''
patchesDim = 128

# output dirs coco format
cDataDir = 'data/mnr'
cTrainImagesDir = cDataDir + '/train2019'
cValidationImagesDir = cDataDir + '/val2019'
cTestImagesDir = cDataDir + '/test2019'
cAnnotationsDir = cDataDir + "/annotations"
directories = [cAnnotationsDir, cTrainImagesDir, cValidationImagesDir, cTestImagesDir]

globalPatchesCounter = 1
globalAnnotationsCounter = 1

# TRAIN, VALIDATION, TEST percentages
splitPoints = [60, 20, 20]
assert (sum(i for i in splitPoints) == 100)

# Ritorna una lista di immagini contenenti solo le staffs, con i rispettivi OFFSET sulle y
# In input si ha l'immagine di partenza
def getStaffsFromImage(img, imgStaff):
    horizontalProjection = np.sum(imgStaff, axis=1)
    pentasSeparators = getPentasSeparators(horizontalProjection)
    staffsAndOffsetsY = []

    # per separatori - 1 volte taglio l'immagine di partenza e la salvo in staff
    for i in range(len(pentasSeparators) - 1):
        start, end = pentasSeparators[i], pentasSeparators[i + 1]
        staff = img[start: end]
        staffsAndOffsetsY.append((staff, (start, end)))

    return staffsAndOffsetsY


# Ritorna una lista di immagini contenenti solo le patch per il dataset
# In input si hanno l'immagine del pentagramma singolo e le dimensioni w, h
def getPatchesFromStaff(staff, w, h):
    patchesAndOffsetsX = []
    l = len(staff)

    transpStaff = staff.transpose()
    # numero di patch sequenziali
    n = int(staff.shape[1] / l)
    for i in range(n):
        # taglio il pentagramma in modo sequenziale
        start, end = i * l, (i + 1) * l
        patch = transpStaff[start: end].transpose()
        # print(str(i*l))
        # plt.imshow(patch, cmap="gray")
        # plt.show()
        patch = resizePatch(patch, w, h)
        patchesAndOffsetsX.append((patch, (start, end)))

        # creo patch casuali di ugual numero a quelle sequenziali
        start = random.randint(0, staff.shape[1] - l)
        end = start + l
        patch = transpStaff[start: end].transpose()
        patch = resizePatch(patch, w, h)
        patchesAndOffsetsX.append((patch, (start, end)))

    return patchesAndOffsetsX


# Ritorna il resize dell'immagine 'patch' secondo le dimensioni w h
def resizePatch(patch, w, h):
    return cv2.resize(patch, dsize=(w, h), interpolation=cv2.INTER_AREA)


# Ritorna la misura dopo aver fatto un resize da startDim a finalDim
# Si e' pensato al fatto che il resize è operazione lineare e quindi il calcolo deriva dalla
# proporzione [start : final = measure : X]
# In input si hanno quindi i 3 valori
def getResizedMeasure(startDimension, finalDimension, measure):
    return int((finalDimension * measure) / startDimension)


# Ritorna l'immagine, quella con sole staff e le note ordinate
# In input si ha il documento XML di supervisione
def initializeImagesAndNotes(doc):
    w = doc[0].uid[31:33]
    p = doc[0].uid[36:38]
    imgPath = "data/CVCMUSCIMA/CvcMuscima-Distortions/ideal/w-" + w + "/image/p0" + p + ".png"
    imgStaffPath = "data/CVCMUSCIMA/CvcMuscima-Distortions/ideal/w-" + w + "/gt/p0" + p + ".png"

    img = mpimg.imread(imgPath)
    imgStaff = mpimg.imread(imgStaffPath)

    notes = getOrderedNotesAnnotations(doc, imgStaff)
    return img, imgStaff, notes


# Ritorna la classe della nota in base agli indici up e low
def getClassFromPositions(u, l):
    return 6 + l - u


def classIdToName(id):
    CLASSES = (
        "__background__",
        "under_staffs",
        "first_line",
        "first_space",
        "second_line",
        "second_space",
        "third_line",
        "third_space",
        "fourth_line",
        "fourth_space",
        "fifth_line",
        "above_staffs",
    )
    return CLASSES[id]


# Cancella i file nelle cartelle di destinazione e crea immagini delle patch e file xml
# In input si hanno le dimensioni delle patches e il documento xml di supervisione (1 IMMAGINE)
def convertToCoco(dimX, dimY, doc, outputDirImages):
    img, imgStaff, notes = initializeImagesAndNotes(doc)
    global globalPatchesCounter
    global globalAnnotationsCounter
    pentasLimits = getPentasLimits(getHorizontalProjection(imgStaff))
    stopValue = ((pentasLimits[0][1] - pentasLimits[0][0]) / 4) * 1.5

    staffs = getStaffsFromImage(img, imgStaff)
    imgStaff = getPreprocessedStaffImage(imgStaff)

    images = []
    annotations = []

    for i, staff in enumerate(staffs):
        patches = getPatchesFromStaff(staff[0], dimX, dimY)
        for patch in patches:
            filename = '{0:012d}.jpg'.format(globalPatchesCounter)
            image = {"id": globalPatchesCounter, "width": dimX, "height": dimY, "file_name": filename}

            mpimg.imsave(outputDirImages + '/' + filename, patch[0], cmap='gray')

            for note in notes[i]:

                # scarta gli elementi nell'xml che non si vogliono
                if not note.clsname.startswith("notehead"):
                    continue

                # scarta gli elementi che non appartengono a questa patch
                # ridimensiona le misure e aggiungi ai boxes i due punti limiti
                t = note.top
                if not staff[1][0] < t < staff[1][1]:
                    continue
                t = t - staff[1][0]
                t = getResizedMeasure(patch[1][1] - patch[1][0], dimX, t)

                l = note.left
                if not patch[1][0] < l < patch[1][1]:
                    continue
                l = l - patch[1][0]
                l = getResizedMeasure(patch[1][1] - patch[1][0], dimX, l)

                w = note.width
                w = getResizedMeasure(patch[1][1] - patch[1][0], dimX, w)
                if l + w >= len(patch[0]):
                    w = len(patch[0]) - l - 1
                if w <= 3:
                    continue
                h = note.height
                h = getResizedMeasure(patch[1][1] - patch[1][0], dimX, h)
                if t + h >= len(patch[0]):
                    h = len(patch[0]) - t - 1
                if h <= 3:
                    continue

                classe = None
                if isInsideStaff(note, pentasLimits):
                    up, low = getInsideStaffNotePosition(imgStaff, note, stopValue)
                    classe = min(max(getClassFromPositions(up, low), 1), 11)
                else:
                    classe = "OutOfStaffs"
                    continue

                area = w*h  # TODO in realtà dovrebbe essere l'area della maschera, che per adesso non viene usata
                annotation = {"id": globalAnnotationsCounter, "image_id": globalPatchesCounter, "category_id": classe,
                              "bbox": [l, t, w, h], "iscrowd": 0, "area": area}
                annotations.append(annotation)
                globalAnnotationsCounter += 1

            images.append(image)

            globalPatchesCounter = globalPatchesCounter + 1

    return images, annotations


# Ritorna True se le cartelle per il salvataggio dei dati esistono, False altrimenti
def checkAndClearDirectories(directoriesList, askForClearing=True):
    # se almeno una delle due cartelle di output esiste, chiedo conferma per sovrascrivere il contenuto
    if askForClearing:
        for dir in directoriesList:
            if os.path.exists(dir):
                response = ""
                while response != 'y' and response != 'n':
                    print(dir + " it's not empty: do you want to clear it and overwrite the content? (y/n)")
                    response = input().lower()
                if response == 'n':
                    return False

    # creo cartelle o elimino contenuto
    for dir in directoriesList:
        if not os.path.exists(dir):
            os.makedirs(dir)
        else:
            clearDirectory(dir)

    return True


# La funzione elimina i file all'interno della cartella che ha percorso = 'directorPath'
def clearDirectory(directoryPath):
    for file in os.listdir(directoryPath):
        file_path = os.path.join(directoryPath, file)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
            # elif os.path.isdir(file_path): shutil.rmtree(file_path)
        except Exception as e:
            print(e)


# genera la stringa JSON che andrà salvata nel file del groundtruth
def getJSONfromDocs(docs, outputDirImages):
    info = {"year": 2019, "version": "0.1", "description": "Coco-style annotations for muscima note recognition",
            "contributor": "Magnolfi and Metaj", "url": "https://github.com/StivenMetaj/DDM_MUSCIMA_Project",
            "date_created": "2019/02/07"}   # info varie sul dataset
    categories = []
    images = []
    annotations = []

    # specifico quali sono la varie classi: l'id è sempre >= 1 perché l'id 0 è riservato al background
    for id in range(1, 12):
        categories.append({"id": id, "name": classIdToName(id)})

    print()
    print("Converting docs...")
    # converto ogni documento nel formato COCO, e aggiorno la lista di immagini e annotazioni
    for docID in tqdm(range(len(docs))):
        doc = docs[docID]

        ims, ans = convertToCoco(patchesDim, patchesDim, doc, outputDirImages)
        images.extend(ims)
        annotations.extend(ans)

    return json.dumps({"info": info, "images": images, "annotations": annotations, "categories": categories})


def main(debug=False):
    # TODO capire differenza tra le due cartelle contenenti il groundtruth in formato xml
    CROPOBJECT_DIR = 'data/CVCMUSCIMA/MUSCIMA++/v1.0/data/cropobjects_manual'
    # CROPOBJECT_DIR = 'data/CVCMUSCIMA/MUSCIMA++/v1.0/data/cropobjects_withstaff'

    print()
    print("Reading list of xml annotations files...")
    cropobject_fnames = [os.path.join(CROPOBJECT_DIR, f) for f in tqdm(os.listdir(CROPOBJECT_DIR))]
    # per debuggare
    if debug:
        cropobject_fnames = cropobject_fnames[70:71]
    cropobject_fnames = sorted(cropobject_fnames)   # ordino in modo da avere riproducibilità

    print()
    print("Reading xml annotations...")
    docs = [parse_cropobject_list(f) for f in tqdm(cropobject_fnames)]

    # mischio casualmente documenti (uso seed per riproducibilità)
    np.random.seed(seed)
    np.random.shuffle(docs)
    random.seed(seed)   # questo seed serve per le patch casuali

    # train/validation/test split
    beginValidationIndex = int(len(docs) * splitPoints[0] / 100)                    # splitPoints[0] = % elementi nel train
    beginTestIndex = int(len(docs) * splitPoints[1] / 100) + beginValidationIndex   # splitPoints[1] = % elementi nel val

    trainDocs = docs[:beginValidationIndex]
    valDocs = docs[beginValidationIndex:beginTestIndex]
    testDocs = docs[beginTestIndex:]

    if not checkAndClearDirectories(directories):
        return

    # per ogni set, genero il corrispondente file json contenente il groundtruth in formato COCO

    with open(cAnnotationsDir + "/instances_train2019.json", "w") as f:
        f.write(getJSONfromDocs(trainDocs, cTrainImagesDir))

    with open(cAnnotationsDir + "/instances_val2019.json", "w") as f:
        f.write(getJSONfromDocs(valDocs, cValidationImagesDir))

    with open(cAnnotationsDir + "/instances_test2019.json", "w") as f:
        f.write(getJSONfromDocs(testDocs, cTestImagesDir))


if __name__ == '__main__':
    main(False)
