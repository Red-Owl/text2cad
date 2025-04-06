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
view.camera.distance = 200
view.camera.center = (50 + 103.2 / 2, 50 + 43.2 / 2, 50 + 51.6 / 2)
view.camera.fov = 60

# Lista per i voxel
voxel_coords = []
voxel_values = []
voxel_colors = []

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
    global voxel_coords, voxel_values, voxel_colors  # Aggiungi voxel_colors
    if not voxel_coords:
        return
    
    voxel_dict = {}
    color_dict = {}
    for idx, (coord, value) in enumerate(zip(voxel_coords, voxel_values)):
        coord_tuple = tuple(coord)
        if value == -1:
            if coord_tuple in voxel_dict:
                del voxel_dict[coord_tuple]
                del color_dict[coord_tuple]
        else:
            if coord_tuple not in voxel_dict:
                voxel_dict[coord_tuple] = value
                color_dict[coord_tuple] = voxel_colors[idx]
    
    voxel_coords = [list(coord) for coord in voxel_dict.keys()]
    voxel_values = list(voxel_dict.values())
    voxel_colors = [color_dict[tuple(coord)] for coord in voxel_coords]  # Aggiorna i colori
    print(f"Rimasti {len(voxel_coords)} voxel dopo la sottrazione")

# Funzione per aggiornare la visualizzazione
def update_visualization():
    global scatter
    if voxel_coords:
        print(f"Aggiornamento rendering con {len(voxel_coords)} voxel")
        coords = np.array(voxel_coords, dtype=np.float32)
        colors = np.array([(1, 1, 1, 1)] * len(voxel_coords), dtype=np.float32)
        if 'scatter' not in globals():
            scatter = scene.visuals.Markers(parent=view.scene)
            grid = scene.visuals.GridLines(parent=view.scene, color=(0.5, 0.5, 0.5, 1))
        scatter.set_data(coords, face_color=colors, size=5)
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

# Nuova funzione per disegnare il teorema di Pitagora






# Aggiungi questa funzione per calcolare i voxel del contorno di un cubo
def get_cube_contour(center, length, width, height):
    contour_coords = []
    x_min, x_max = int(center[0] - length//2), int(center[0] + length//2)
    y_min, y_max = int(center[1] - width//2), int(center[1] + width//2)
    z_min, z_max = int(center[2] - height//2), int(center[2] + height//2)
    
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            for z in range(z_min, z_max + 1):
                if (x in (x_min, x_max) and y in (y_min, y_max)) or \
                   (x in (x_min, x_max) and z in (z_min, z_max)) or \
                   (y in (y_min, y_max) and z in (z_min, z_max)):
                    contour_coords.append([x, y, z])
    return contour_coords

# Modifica la funzione draw_pythagorean_theorem
@torch.no_grad()
def draw_pythagorean_theorem(center):
    global voxel_coords, voxel_values, voxel_colors
    voxel_coords.clear()
    voxel_values.clear()
    voxel_colors = []
    
    # Dimensioni del triangolo: a = 40, b = 50, c = sqrt(4100) ≈ 64
    a, b = 40, 50
    c = int(np.sqrt(a**2 + b**2))  # ≈ 64
    
    # Vertici del triangolo sul piano z = 0
    A = (int(center[0]), int(center[1]), 0)  # Angolo retto
    B = (int(center[0] + a), int(center[1]), 0)  # Fine cateto a
    C = (int(center[0]), int(center[1] + b), 0)  # Fine cateto b
    
    # Disegna il triangolo (contorno verde)
    # Cateto a
    for x in range(A[0], B[0] + 1):
        voxel_coords.append([x, A[1], 0])
        voxel_values.append(1)
        voxel_colors.append([0, 1, 0, 1])  # Verde
    # Cateto b
    for y in range(A[1], C[1] + 1):
        voxel_coords.append([A[0], y, 0])
        voxel_values.append(1)
        voxel_colors.append([0, 1, 0, 1])  # Verde
    # Ipotenusa c (linea discreta)
    steps = max(a, b)
    for i in range(steps + 1):
        x = int(B[0] - (a * i / steps))
        y = int(A[1] + (b * i / steps))
        voxel_coords.append([x, y, 0])
        voxel_values.append(1)
        voxel_colors.append([0, 1, 0, 1])  # Verde
    
    # Disegna i quadrati (contorni con colori diversi, sovrapposti ai lati del triangolo)
    # Quadrato su a (sotto il cateto a, rosso)
    center_a = (center[0] + a/2, center[1] - a/2, 0)  # Centro sotto il cateto a
    contour_a = get_cube_contour(center_a, a, a, 1)
    for coord in contour_a:
        # Evita di sovrascrivere il colore verde del cateto a
        if not (coord[0] >= A[0] and coord[0] <= B[0] and coord[1] == A[1] and coord[2] == 0):
            voxel_coords.append(coord)
            voxel_values.append(1)
            voxel_colors.append([1, 0, 0, 1])  # Rosso
    
    # Quadrato su b (a sinistra del cateto b, blu)
    center_b = (center[0] - b/2, center[1] + b/2, 0)  # Centro a sinistra del cateto b
    contour_b = get_cube_contour(center_b, b, b, 1)
    for coord in contour_b:
        # Evita di sovrascrivere il colore verde del cateto b
        if not (coord[0] == A[0] and coord[1] >= A[1] and coord[1] <= C[1] and coord[2] == 0):
            voxel_coords.append(coord)
            voxel_values.append(1)
            voxel_colors.append([0, 0, 1, 1])  # Blu
    
    # Quadrato su c (orientato lungo l'ipotenusa, giallo)
    # Calcola il centro del quadrato sull'ipotenusa
    center_c = ((B[0] + C[0])/2, (B[1] + C[1])/2, 0)
    # Calcola l'angolo dell'ipotenusa
    angle = np.arctan2(C[1] - B[1], C[0] - B[0])  # atan2(50, -40)
    # Vettore perpendicolare (ruotato di 90 gradi in senso orario per essere sotto il triangolo)
    perp_vec = ((C[1] - B[1]), -(C[0] - B[0]))  # (50, 40) invece di (-50, -40)
    # Normalizza per la lunghezza c/2
    norm = np.sqrt(perp_vec[0]**2 + perp_vec[1]**2)
    perp_vec = (perp_vec[0] * (c/2) / norm, perp_vec[1] * (c/2) / norm)
    # Centro del quadrato spostato lungo la direzione perpendicolare
    center_c = (center_c[0] + perp_vec[0], center_c[1] + perp_vec[1], 0)
    contour_c = get_rotated_square_contour(center_c, c, angle)
    for coord in contour_c:
        # Evita di sovrascrivere il colore verde dell'ipotenusa
        is_on_hypotenuse = False
        for i in range(steps + 1):
            x_hyp = int(B[0] - (a * i / steps))
            y_hyp = int(A[1] + (b * i / steps))
            if coord[0] == x_hyp and coord[1] == y_hyp and coord[2] == 0:
                is_on_hypotenuse = True
                break
        if not is_on_hypotenuse:
            voxel_coords.append(coord)
            voxel_values.append(1)
            voxel_colors.append([1, 1, 0, 1])  # Giallo
    
    apply_negative_voxels()
    
    # Aggiorna la visualizzazione con i colori
    global scatter
    if voxel_coords:
        print(f"Aggiornamento rendering con {len(voxel_coords)} voxel")
        coords = np.array(voxel_coords, dtype=np.float32)
        colors = np.array(voxel_colors, dtype=np.float32)
        if 'scatter' not in globals():
            scatter = scene.visuals.Markers(parent=view.scene)
            grid = scene.visuals.GridLines(parent=view.scene, color=(0.5, 0.5, 0.5, 1))
        scatter.set_data(coords, face_color=colors, size=5)
        canvas.update()
    else:
        print("Nessun voxel da visualizzare")
    print(f"Teorema di Pitagora disegnato con centro in {center}")


def get_rotated_square_contour(center, size, angle):
    contour_coords = []
    half_size = size // 2
    # Genera i voxel del contorno in coordinate locali
    for x in range(-half_size, half_size + 1):
        for y in range(-half_size, half_size + 1):
            if x in (-half_size, half_size) or y in (-half_size, half_size):
                # Ruota il punto (x, y) di angle attorno all'origine
                x_rot = x * np.cos(angle) - y * np.sin(angle)
                y_rot = x * np.sin(angle) + y * np.cos(angle)
                # Trasla al centro
                x_rot += center[0]
                y_rot += center[1]
                contour_coords.append([int(x_rot), int(y_rot), 0])
    return contour_coords



# Funzione per disegnare una forma personalizzata dal database
def draw_custom_shape(shape_name, center, parameters, negative=False):
    shape_definition = load_shape_definition(shape_name)
    if not shape_definition:
        print(f"Definizione per la forma '{shape_name}' non trovata nel database.")
        return False

    if shape_definition['type'] != "custom":
        print(f"Tipo di definizione '{shape_definition['type']}' non supportato per forme personalizzate.")
        return False

    params = shape_definition['parameters']
    operations = shape_definition['operations']

    outer_length = params['inner_length'] + 2 * params['wall_thickness']
    outer_width = params['inner_width'] + 2 * params['wall_thickness']
    outer_height = params['inner_height'] + params['wall_thickness']

    for op in operations:
        op_type = op['type']
        op_negative = op.get('negative', False)

        if op_type == "cube":
            length = eval(op['length'], params)
            width = eval(op['width'], params)
            height = eval(op['height'], params)

            if op['center'] == "computed":
                if op == operations[0]:
                    op_center = (center[0] + outer_length / 2, center[1] + outer_width / 2, center[2] + outer_height / 2)
                elif op == operations[1]:
                    op_center = (center[0] + outer_length / 2, center[1] + outer_width / 2, center[2] + outer_height / 2 + params['wall_thickness'] / 2)
                elif op == operations[2]:
                    op_center = (center[0] + outer_length / 2, center[1] + outer_width / 2, center[2] + outer_height - params['wall_thickness'] / 2)
                elif op == operations[3]:
                    lid_center_x = center[0] + outer_length + 5 + length / 2
                    lid_center_y = center[1] + outer_width / 2
                    lid_center_z = center[2] + height / 2
                    op_center = (lid_center_x, lid_center_y, lid_center_z)
                else:
                    op_center = center
            else:
                op_center = center

            draw_cube(op_center, length, width, height, negative=op_negative)

        elif op_type == "cylinder":
            radius = eval(op['radius'], params)
            height = eval(op['height'], params)

            if op['center'] == "computed":
                support_center_x = center[0] + params['screw_distance_from_edge'] + params['wall_thickness']
                support_center_y = center[1] + outer_width / 2
                if op == operations[4]:
                    op_center = (support_center_x, support_center_y, center[2])
                elif op == operations[5]:
                    op_center = (support_center_x, support_center_y, center[2])
                else:
                    op_center = center
            else:
                op_center = center

            draw_cylinder(op_center, radius, height, negative=op_negative)
    
    return True
def get_cube_contour(center, length, width, height):
    contour_coords = []
    x_min, x_max = int(center[0] - length//2), int(center[0] + length//2)
    y_min, y_max = int(center[1] - width//2), int(center[1] + width//2)
    z_min, z_max = int(center[2] - height//2), int(center[2] + height//2)
    
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            for z in range(z_min, z_max + 1):
                if (x in (x_min, x_max) and y in (y_min, y_max)) or \
                   (x in (x_min, x_max) and z in (z_min, z_max)) or \
                   (y in (y_min, y_max) and z in (z_min, z_max)):
                    contour_coords.append([x, y, z])
    return contour_coords
    
# Parser del chatbot modificato
def parse_command(command):
    global voxel_coords, voxel_values, running

    command = command.lower()

    position_match = re.search(r"at\s+(\d+),(\d+),(\d+)", command)
    position = (int(position_match.group(1)), int(position_match.group(2)), int(position_match.group(3))) if position_match else None
    
    description_match = re.search(r"description\s+'([^']+)'", command)
    description = description_match.group(1) if description_match else None
    
    negative = "negative" in command

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
        elif "draw pythagorean theorem" in command:
            if not position:
                return "Comando incompleto: specificare la posizione (es. 'Draw pythagorean theorem at 150,150,0')"
            draw_pythagorean_theorem(position)
            object_id = save_object_to_db("pythagorean_theorem", {}, position, False, description)
            return f"Teorema di Pitagora disegnato a {position} (ID: {object_id})"
        elif "save stl" in command:
            filename = "output.stl"
            return export_to_stl(filename)
        elif "load objects" in command:
            object_id_match = re.search(r"id\s+(\d+)", command)
            object_id = int(object_id_match.group(1)) if object_id_match else None
            objects = load_objects_from_db(object_id)
            if not objects:
                return "Nessun oggetto trovato."
            
            voxel_coords.clear()
            voxel_values.clear()
            
            loaded_objects = 0
            for obj in objects:
                position = (obj['aw_position_x'], obj['aw_position_y'], obj['aw_position_z'])
                params = json.loads(obj['aw_parameters'])
                negative = obj['aw_negative']
                if obj['aw_type'] == "pythagorean_theorem":
                    draw_pythagorean_theorem(position)
                    loaded_objects += 1
                else:
                    success = draw_custom_shape(obj['aw_type'], position, params, negative)
                    if success:
                        loaded_objects += 1
            return f"Caricati {loaded_objects} oggetti (su {len(objects)} totali)."
        elif "exit" in command:
            global running
            running = False
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
    websocket_thread.join()

if __name__ == "__main__":
    main()