import torch
import numpy as np
import trimesh
from vispy import app, scene
import vispy
import asyncio
import websockets
import threading
import re
import mysql.connector
import json
import sys

# Forza il backend PyQt5
vispy.use('pyqt5')

# Configurazione
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SPACE_SIZE = 300  # Aumentiamo lo spazio per includere il coperchio accanto alla scatola

# Configurazione del database MySQL
db_config = {
    'host': '127.0.0.1',
    'user': 'user2',
    'password': 'password',
    'database': '3d_objects',
    'port': '3307'
}
# Canvas per il rendering
canvas = scene.SceneCanvas(keys='interactive', size=(800, 600), show=True)
view = canvas.central_widget.add_view()
view.camera = 'turntable'
view.camera.distance = 200  # Riduciamo la distanza per avvicinarci alla scatola
view.camera.center = (50 + 103.2 / 2, 50 + 43.2 / 2, 50 + 51.6 / 2)  # Centriamo sulla scatola
view.camera.fov = 60

# Lista per i voxel
voxel_coords = []
voxel_values = []

# Flag per controllare l'uscita
running = True

# Funzione per connettersi al database
def get_db_connection():
    return mysql.connector.connect(**db_config)

# Funzione per salvare un oggetto nel database
def save_object_to_db(obj_type, parameters, position, is_negative, description=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO aige_treedee (aw_type, aw_description, aw_parameters, aw_position_x, aw_position_y, aw_position_z, aw_negative)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    params = (obj_type, description, json.dumps(parameters), position[0], position[1], position[2], is_negative)
    cursor.execute(query, params)
    conn.commit()
    object_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return object_id

# Funzione per recuperare tutti gli oggetti dal database
def load_objects_from_db(object_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if object_id:
        query = "SELECT * FROM aige_treedee WHERE AW = %s"
        cursor.execute(query, (object_id,))
    else:
        query = "SELECT * FROM aige_treedee"
        cursor.execute(query)
    objects = cursor.fetchall()
    cursor.close()
    conn.close()
    return objects

# Funzione per caricare la definizione di una forma dal database
def load_shape_definition(shape_name):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = "SELECT shape_definition FROM aige_shapes WHERE shape_name = %s"
    cursor.execute(query, (shape_name,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return json.loads(result['shape_definition']) if result else None

# Funzione per aggiungere un cubo
@torch.no_grad()
def draw_cube(center, length, width, height, negative=False):
    x = torch.arange(int(center[0] - length//2), int(center[0] + length//2 + 1), device=DEVICE, dtype=torch.int64)
    y = torch.arange(int(center[1] - width//2), int(center[1] + width//2 + 1), device=DEVICE, dtype=torch.int64)
    z = torch.arange(int(center[2] - height//2), int(center[2] + height//2 + 1), device=DEVICE, dtype=torch.int64)
    x, y, z = torch.meshgrid(x, y, z, indexing='ij')
    
    coords = torch.stack([x, y, z], dim=-1).reshape(-1, 3).cpu().numpy()
    valid = (coords >= 0) & (coords < SPACE_SIZE)
    valid = np.all(valid, axis=1)
    coords = coords[valid]
    
    print(f"Generati {len(coords)} voxel per il cubo di dimensioni {length}x{width}x{height}")
    voxel_coords.extend(coords.tolist())
    voxel_values.extend([1 if not negative else -1] * len(coords))
    
    apply_negative_voxels()
    update_visualization()

# Funzione per aggiungere un cilindro
@torch.no_grad()
def draw_cylinder(center, radius, height, negative=False):
    r_int = int(radius) + 1
    x = torch.arange(int(center[0] - r_int), int(center[0] + r_int + 1), device=DEVICE, dtype=torch.int64)
    y = torch.arange(int(center[1] - r_int), int(center[1] + r_int + 1), device=DEVICE, dtype=torch.int64)
    z = torch.arange(int(center[2]), int(center[2] + height + 1), device=DEVICE, dtype=torch.int64)
    x, y, z = torch.meshgrid(x, y, z, indexing='ij')
    
    dist = torch.sqrt((x - center[0])**2 + (y - center[1])**2)
    mask = dist <= radius
    
    coords = torch.nonzero(mask).cpu().numpy()
    if len(coords) == 0:
        print("Nessun voxel generato per il cilindro.")
        return
    
    # Calcola le coordinate finali
    coords = coords.astype(np.float32)
    coords[:, 0] += center[0] - r_int
    coords[:, 1] += center[1] - r_int
    coords[:, 2] += center[2]
    
    valid = (coords >= 0) & (coords < SPACE_SIZE)
    valid = np.all(valid, axis=1)
    coords = coords[valid]
    
    print(f"Generati {len(coords)} voxel per il cilindro di raggio {radius} e altezza {height}")
    voxel_coords.extend(coords.tolist())
    voxel_values.extend([1 if not negative else -1] * len(coords))
    
    apply_negative_voxels()
    update_visualization()

# Funzione per applicare la sottrazione dei voxel negativi
def apply_negative_voxels():
    global voxel_coords, voxel_values
    if not voxel_coords:
        return
    
    voxel_dict = {}
    for coord, value in zip(voxel_coords, voxel_values):
        coord_tuple = tuple(coord)
        if value == -1:
            if coord_tuple in voxel_dict:
                del voxel_dict[coord_tuple]
        else:
            if coord_tuple not in voxel_dict:
                voxel_dict[coord_tuple] = value
    
    voxel_coords = [list(coord) for coord in voxel_dict.keys()]
    voxel_values = list(voxel_dict.values())
    print(f"Rimasti {len(voxel_coords)} voxel dopo la sottrazione")

# Funzione per aggiornare la visualizzazione
def update_visualization():
    global scatter
    if voxel_coords:
        print(f"Aggiornamento rendering con {len(voxel_coords)} voxel")
        coords = np.array(voxel_coords, dtype=np.float32)
        colors = np.array([(1, 1, 1, 1)] * len(voxel_coords), dtype=np.float32)  # Cambiamo il colore in bianco
        if 'scatter' not in globals():
            scatter = scene.visuals.Markers(parent=view.scene)
            grid = scene.visuals.GridLines(parent=view.scene, color=(0.5, 0.5, 0.5, 1))
        scatter.set_data(coords, face_color=colors, size=5)  # Aumentiamo la dimensione dei voxel
        canvas.update()
    else:
        print("Nessun voxel da visualizzare")

# Esportazione STL
def export_to_stl(filename, unit="mm"):
    if not voxel_coords:
        print("Nessun voxel da esportare!")
        return "Errore: Nessun voxel da esportare"
    vertices = np.array(voxel_coords)
    if len(vertices) == 0:
        print("Nessun voxel positivo da esportare!")
        return "Errore: Nessun voxel positivo da esportare"
    mesh = trimesh.voxel.ops.points_to_marching_cubes(vertices)
    scale = 1.0 if unit == "mm" else 0.1 if unit == "cm" else 0.001
    mesh.apply_scale(scale)
    mesh.export(filename)
    print(f"File STL salvato come {filename}")
    return f"File STL salvato come {filename}"

# Funzione per disegnare una forma personalizzata dal database
def draw_custom_shape(shape_name, center, parameters, negative=False):
    shape_definition = load_shape_definition(shape_name)
    if not shape_definition:
        print(f"Definizione per la forma '{shape_name}' non trovata nel database.")
        return False

    if shape_definition['type'] != "custom":
        print(f"Tipo di definizione '{shape_definition['type']}' non supportato per forme personalizzate.")
        return False

    # Parametri della forma
    params = shape_definition['parameters']
    operations = shape_definition['operations']

    # Calcola le dimensioni esterne della scatola
    outer_length = params['inner_length'] + 2 * params['wall_thickness']
    outer_width = params['inner_width'] + 2 * params['wall_thickness']
    outer_height = params['inner_height'] + params['wall_thickness']

    # Esegui ogni operazione
    for op in operations:
        op_type = op['type']
        op_negative = op.get('negative', False)

        if op_type == "cube":
            length = eval(op['length'], params)
            width = eval(op['width'], params)
            height = eval(op['height'], params)

            # Calcola il centro in base all'operazione
            if op['center'] == "computed":
                if op == operations[0]:  # Scatola esterna
                    op_center = (center[0] + outer_length / 2, center[1] + outer_width / 2, center[2] + outer_height / 2)
                elif op == operations[1]:  # Interno cavo
                    op_center = (center[0] + outer_length / 2, center[1] + outer_width / 2, center[2] + outer_height / 2 + params['wall_thickness'] / 2)
                elif op == operations[2]:  # Rimuovi la parte superiore per vedere l'interno
                    op_center = (center[0] + outer_length / 2, center[1] + outer_width / 2, center[2] + outer_height - params['wall_thickness'] / 2)
                elif op == operations[3]:  # Coperchio (posizionato accanto alla scatola)
                    # Posiziona il coperchio a destra della scatola, con il fondo allineato
                    lid_center_x = center[0] + outer_length + 5 + length / 2  # 5 mm di spazio
                    lid_center_y = center[1] + outer_width / 2
                    lid_center_z = center[2] + height / 2  # Fondo del coperchio allineato con il fondo della scatola
                    op_center = (lid_center_x, lid_center_y, lid_center_z)
                else:
                    op_center = center
            else:
                op_center = center

            draw_cube(op_center, length, width, height, negative=op_negative)

        elif op_type == "cylinder":
            radius = eval(op['radius'], params)
            height = eval(op['height'], params)

            # Calcola il centro in base all'operazione
            if op['center'] == "computed":
                support_center_x = center[0] + params['screw_distance_from_edge'] + params['wall_thickness']
                support_center_y = center[1] + outer_width / 2
                if op == operations[4]:  # Supporto per la vite
                    op_center = (support_center_x, support_center_y, center[2])
                elif op == operations[5]:  # Foro per la vite
                    op_center = (support_center_x, support_center_y, center[2])
                else:
                    op_center = center
            else:
                op_center = center

            draw_cylinder(op_center, radius, height, negative=op_negative)
    
    return True

# Parser del chatbot
def parse_command(command):
    global voxel_coords, voxel_values, running

    command = command.lower()

    # Estrai la posizione, se specificata
    position_match = re.search(r"at\s+(\d+),(\d+),(\d+)", command)
    position = (int(position_match.group(1)), int(position_match.group(2)), int(position_match.group(3))) if position_match else None
    
    # Estrai la descrizione, se specificata
    description_match = re.search(r"description\s+'([^']+)'", command)
    description = description_match.group(1) if description_match else None
    
    negative = "negative" in command

    # Gestione dei comandi
    try:
        if "draw a box" in command:
            if not position:
                return "Comando incompleto: specificare la posizione (es. 'Draw a box at 50,50,50')"
            parameters = {}
            success = draw_custom_shape("box", position, parameters, negative)
            if not success:
                return f"Errore: Impossibile disegnare la scatola a {position}"
            object_id = save_object_to_db("box", parameters, position, negative, description)
            return f"Scatola disegnata a {position} (ID: {object_id})"
        elif "save stl" in command:
            filename = "output.stl"
            return export_to_stl(filename)
        elif "load objects" in command:
            object_id_match = re.search(r"id\s+(\d+)", command)
            object_id = int(object_id_match.group(1)) if object_id_match else None
            objects = load_objects_from_db(object_id)
            if not objects:
                return "Nessun oggetto trovato."
            
            # Cancella lo spazio attuale
            voxel_coords.clear()
            voxel_values.clear()
            
            # Ridisegna gli oggetti
            loaded_objects = 0
            for obj in objects:
                position = (obj['aw_position_x'], obj['aw_position_y'], obj['aw_position_z'])
                params = json.loads(obj['aw_parameters'])
                negative = obj['aw_negative']
                success = draw_custom_shape(obj['aw_type'], position, params, negative)
                if success:
                    loaded_objects += 1
            return f"Caricati {loaded_objects} oggetti (su {len(objects)} totali)."
        elif "exit" in command:
            global running
            running = False
            # Chiude il ciclo di eventi di VisPy
            app.quit()
            return "Chiusura dell'applicazione..."
        else:
            return "Comando non riconosciuto"
    except Exception as e:
        print(f"Errore durante il parsing del comando: {e}")
        return "Comando incompleto o non riconosciuto"

# Server WebSocket
async def handle_websocket(websocket, path):
    global running
    try:
        async for message in websocket:
            print(f"Ricevuto comando: {message}")
            response = parse_command(message)
            await websocket.send(response)
            if not running:
                break
    except websockets.ConnectionClosed:
        print("Connessione WebSocket chiusa dal client")
    except Exception as e:
        print(f"Errore nel WebSocket: {e}")
        await websocket.send(f"Errore: {str(e)}")
    finally:
        if not running:
            print("Terminazione del server WebSocket...")
            await websocket.close()

# Funzione per avviare il server WebSocket in un thread separato
def start_websocket_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_server())
    loop.close()

async def websocket_server():
    server = await websockets.serve(handle_websocket, "localhost", 8765)
    print("Server WebSocket avviato su ws://localhost:8765")
    while running:
        await asyncio.sleep(1)
    server.close()
    await server.wait_closed()

# Avvia il server WebSocket e il rendering
def main():
    websocket_thread = threading.Thread(target=start_websocket_server)
    websocket_thread.start()
    app.run()
    # Aspetta che il thread del WebSocket termini
    websocket_thread.join()

# Esegui
if __name__ == "__main__":
    main()