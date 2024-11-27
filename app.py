from flask import Flask, jsonify, request, session, make_response
from flask_cors import CORS
import mysql.connector
import uuid  
from neo4j import GraphDatabase
import os



app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = 'e7ef771e4cf86b5663e2e973510f3cb63c769f2b3e7fe429'

# ================================================================================================================
# Conexión para base de datos relacionales
def get_db_connection():
    connection = mysql.connector.connect(
        host='autorack.proxy.rlwy.net',
        user='Nilson',
        password='nilson',
        database='mydb',
        port=29880
    )
    return connection

# ======================================================================================================================
# Clase para manejar la conexión con Neo4j
class Neo4jConnection:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def execute_query(self, query, parameters=None):
        with self.driver.session() as session:
            result = session.run(query, parameters)
            return [record for record in result]

# Configuración de la conexión a Neo4j
neo4j_conn = Neo4jConnection(
    uri=os.getenv("NEO4J_URI", "bolt://44.201.216.233:7687"),
    user=os.getenv("NEO4J_USER", "neo4j"),
    password=os.getenv("NEO4J_PASSWORD", "death-weeds-swimmer")
)
# ======================================================================================================================
# Inicio de sesión
@app.route('/data', methods=['POST'])
def get_data():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute('SELECT DireccionCorreo, password,idinformacion_Persona FROM informacion_Persona WHERE DireccionCorreo = %s AND password = %s', (email, password))
    rows = cursor.fetchall()
    cursor.close()
    connection.close()

    if rows:
        # Guardar el email en la sesión
        session['email'] = email
        session['idinformacion_Persona'] = rows[0]['idinformacion_Persona']
        print(session['idinformacion_Persona'])
        
        # Generar un identificador único para la cookie
        session_id = str(uuid.uuid4())

        # Crear una respuesta con la cookie
        response = make_response(jsonify(rows))
        response.set_cookie('session_id', session_id, httponly=True, samesite='Strict')
        
        return response, 200
    else:
        return jsonify({"message": "Invalid email or password"}), 401

# Crear usuario
@app.route('/create_user', methods=['POST'])
def create_user():
    data = request.get_json()

    # Validación de datos obligatorios
    required_fields = ['DNI', 'DireccionCorreo', 'FechaNacimiento', 'Nombre', 'password']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"message": f"{field} is required"}), 400

    # Variables
    DNI = data['DNI']
    DireccionCorreo = data['DireccionCorreo']
    FechaNacimiento = data['FechaNacimiento']
    Nombre = data['Nombre']
    password = data['password']

    Departamento = data.get('Departamento')
    Provincia = data.get('Provincia')
    Distrito = data.get('Distrito')
    Direccion = data.get('Direccion')

    # Inserción en ambas bases
    try:
        # 1. Inserta en MySQL
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute('''
            INSERT INTO informacion_Persona (DNI, DireccionCorreo, FechaNacimiento, Nombre, password)
            VALUES (%s, %s, %s, %s, %s)
        ''', (DNI, DireccionCorreo, FechaNacimiento, Nombre, password))
        user_id = cursor.lastrowid

        # Insertar en direccion_Persona si hay datos
        if Departamento or Provincia or Distrito or Direccion:
            cursor.execute('''
                INSERT INTO direccion_Persona (informacion_Persona_idinformacion_Persona, direccion, departamento, provincia, distrito)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user_id, Direccion, Departamento, Provincia, Distrito))
            
            # 2. Inserta en Neo4j DOMICILIO DE LA PERSONA REGISTRADA
            query = '''
            MERGE (p:PERSONA { name: $name,id: $user_id, dni: $dni, FechaNacimiento:$FechaNacimiento, correo: $correo})
            MERGE (d:DIRECCION { direccion: $direccion, departamento: $departamento, provincia: $provincia, distrito: $distrito})
            MERGE (p)-[:VIVE_EN]->(d)
            RETURN p, d
            '''
            
            neo4j_conn.execute_query(query, {
                "user_id": user_id,  # Usar el id de MySQL
                "name": Nombre,
                "dni": DNI,
                "correo": DireccionCorreo,
                "FechaNacimiento": FechaNacimiento,
                "direccion": Direccion,
                "departamento": Departamento,
                "provincia": Provincia,
                "distrito": Distrito
            })
            
        else:
            # En caso de no tener dirección (Poco probable), pero en caso pueda ocurrir.
            query = '''
            MERGE (p:PERSONA { id: $user_id, dni: $dni, correo: $correo, name: $name})
            RETURN p
            '''
            neo4j_conn.execute_query(query, {
                "user_id": user_id,  # Usar el id de MySQL
                "dni": DNI,
                "correo": DireccionCorreo,
                "name": Nombre
            })

        connection.commit()
    
        return jsonify({"message": "User created successfully"}), 201

    except Exception as e:
        print(f"Error al crear usuario: {e}")  # Depuración
        return jsonify({"message": f"Error creating user: {str(e)}"}), 500

    

    finally:
        cursor.close()
        connection.close()
        


# Para el inbox
@app.route('/api/inbox', methods=['GET'])
def get_inbox():
    # Obtener el ID del usuario desde la sesión
    user_id = session.get('idinformacion_Persona')
    if not user_id:
        return jsonify({"message": "User not logged in"}), 401

    try:
        # Conexión a la base de datos
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Consulta para obtener las solicitudes específicas del usuario
        cursor.execute('''
            SELECT id_solicitud, objeto_pedido,objeto_ofrecido, estado_solicitud, fecha_solicitud
            FROM inbox_Persona
            WHERE informacion_Persona_idinformacion_Persona = %s
        ''', (user_id,))
        rows = cursor.fetchall()

        cursor.close()
        connection.close()

        # Retorna las solicitudes como JSON
        return jsonify(rows), 200

    except mysql.connector.Error as err:
        print(f"Error al obtener el inbox: {err}")
        return jsonify({"message": "Error fetching inbox data"}), 500
        
#Agregar objetos
@app.route('/addObject', methods=['POST'])
def add_object():
    informacion_Persona_idinformacion_Persona = session.get('idinformacion_Persona')
    if not informacion_Persona_idinformacion_Persona:
        return jsonify({"message": "User not logged in"}), 401

    data = request.get_json()
    Nombre = data.get('Nombre')
    Descripcion = data.get('Descripcion')
    URL_Imagen = data.get('URL_Imagen')
    URL_Video = data.get('URL_Video')
    categoria = data.get('categoria')
    estado_estetico = data.get('estado_estetico')
    estado_funcional = data.get('estado_funcional')
    estado_garantia = data.get('estado_garantia')

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Insertar  un objeto en la tabla objeto
        cursor.execute('''
            INSERT INTO objeto (Nombre, Descripcion, URL_Imagen, URL_Video, informacion_Persona_idinformacion_Persona, categoria) 
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (Nombre, Descripcion, URL_Imagen, URL_Video, informacion_Persona_idinformacion_Persona, categoria))
        
        # Obtener el id del objeto recién insertado
        idobjeto = cursor.lastrowid
        
        # 2. Inserta en Neo4j el objeto de la persona
        query = '''
        MERGE (p:PERSONA { id: $user_id})
        MERGE (o:OBJETO { name: $name,id: $id,descripcion: $descripcion, url_imagen: $url_imagen, url_video: $url_video, categoria: $categoria})
        MERGE (p)-[:TIENE]->(o)
        RETURN p, o
        '''
        neo4j_conn.execute_query(query, {
            "user_id": informacion_Persona_idinformacion_Persona,
            "name": Nombre,
            "id": idobjeto,
            "descripcion": Descripcion,
            "url_imagen": URL_Imagen,
            "url_video": URL_Video,
            "categoria": categoria
            
            
        })
            
      
        # Insertar una reseña la tabla reseñas_objetos
        cursor.execute('''
            INSERT INTO reseñas_objetos (objeto_idobjeto, estado_estético, estado_funcional, estado_garantia) 
            VALUES (%s, %s, %s, %s)
        ''', (idobjeto, estado_estetico, estado_funcional, estado_garantia))
        
        query = '''
        MATCH (o:OBJETO { id: $id})
        MERGE (r:RESEÑA {estado_estetico: $estado_estetico, estado_funcional: $estado_funcional, estado_garantia: $estado_garantia})
        MERGE (o)-[:TIENE_RESEÑA]->(r)
        '''
        neo4j_conn.execute_query(query, {
            "id": idobjeto,
            "estado_estetico": estado_estetico,
            "estado_funcional": estado_funcional,
            "estado_garantia": estado_garantia
        })
        
        
        connection.commit()
    except mysql.connector.Error as err:
        connection.rollback()
        return jsonify({"message": f"Error: {err}"}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({
        "message": "Object and review added successfully",
        "object_id": idobjeto
    }), 201



#Agregar objetos al banco
#Agregar objetos al banco
#Agregar objetos al banco
@app.route('/addObjectbank', methods=['POST'])
def add_objectbank():
    informacion_Persona_idinformacion_Persona = session.get('idinformacion_Persona')
    if not informacion_Persona_idinformacion_Persona:
        return jsonify({"message": "User not logged in"}), 401

    data = request.get_json()
    Nombre = data.get('Nombre')
    Descripcion = data.get('Descripcion')
    URL_Imagen = data.get('URL_Imagen')
    URL_Video = data.get('URL_Video')
    categoria = data.get('categoria')
    estado_estetico = data.get('estado_estetico')
    estado_funcional = data.get('estado_funcional')
    estado_garantia = data.get('estado_garantia')

    if not Nombre or not categoria:
        return jsonify({"message": "Nombre and categoria are required"}), 400

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Insertar objeto en la base de datos MySQL
        cursor.execute('''
            INSERT INTO objeto (Nombre, Descripcion, URL_Imagen, URL_Video, informacion_Persona_idinformacion_Persona, categoria) 
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (Nombre, Descripcion, URL_Imagen, URL_Video, informacion_Persona_idinformacion_Persona, categoria))
        
        # Obtener el ID del objeto recién insertado
        idobjeto = cursor.lastrowid

        # Insertar reseñas en MySQL
        cursor.execute('''
            INSERT INTO reseñas_objetos (objeto_idobjeto, estado_estético, estado_funcional, estado_garantia) 
            VALUES (%s, %s, %s, %s)
        ''', (idobjeto, estado_estetico, estado_funcional, estado_garantia))

        # Crear nodos y relaciones en Neo4j
        query = '''
        MERGE (o:OBJETO { id: $id })
        ON CREATE SET o.name = $name, o.descripcion = $descripcion, o.url_imagen = $url_imagen, o.url_video = $url_video, o.categoria = $categoria
        MERGE (r:RESEÑA { id: apoc.create.uuid(), estado_estetico: $estado_estetico, estado_funcional: $estado_funcional, estado_garantia: $estado_garantia })
        ON CREATE SET r.name = $default_name
        CREATE (o)-[:TIENE_RESEÑA]->(r)
        '''
        neo4j_conn.execute_query(query, {
            "id": idobjeto,
            "name": Nombre,
            "default_name": f"Reseña_Objeto_{idobjeto}",
            "descripcion": Descripcion,
            "url_imagen": URL_Imagen,
            "url_video": URL_Video,
            "categoria": categoria,
            "estado_estetico": estado_estetico,
            "estado_funcional": estado_funcional,
            "estado_garantia": estado_garantia
        })

        # Relacionar la persona existente con el objeto subido
        query = '''
        MERGE (p:PERSONA { id: $user_id})
        MERGE (o:OBJETO { name: $name,id: $id,descripcion: $descripcion, url_imagen: $url_imagen, url_video: $url_video, categoria: $categoria})
        MERGE (p)-[:AGREGO]->(o)
        RETURN p, o
        '''
        neo4j_conn.execute_query(query, {
            "user_id": informacion_Persona_idinformacion_Persona,
            "name": Nombre,
            "id": idobjeto,
            "descripcion": Descripcion,
            "url_imagen": URL_Imagen,
            "url_video": URL_Video,
            "categoria": categoria
        })

        # Actualizar has_ticket en MySQL
        cursor.execute('''
            UPDATE informacion_Persona 
            SET has_ticket = has_ticket + 1 
            WHERE idinformacion_Persona = %s
        ''', (informacion_Persona_idinformacion_Persona,))

        # Insertar en banco y relacionar en Neo4j
        cursor.execute('''
            INSERT INTO banco (dejado_por, objeto_idobjeto) 
            VALUES (%s, %s)
        ''', (informacion_Persona_idinformacion_Persona, idobjeto))
        banco_id_banca = cursor.lastrowid

        query = '''
        MATCH (o:OBJETO { id: $id })
        MERGE (b:BANCO { id_banco: $id_banco })
        ON CREATE SET b.name = $default_name
        CREATE (o)-[:RECEPCIONADO]->(b)
        '''
        neo4j_conn.execute_query(query, {
            "id_banco": banco_id_banca,
            "id": idobjeto,
            "default_name": f"Stored_Objeto_{idobjeto}"
        })

        # Crear ticket en MySQL y Neo4j
        numero_de_ticket = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO ticket (banco_id_banca, informacion_Persona_idinformacion_Persona, numero_de_ticket) 
            VALUES (%s, %s, %s)
        ''', (banco_id_banca, informacion_Persona_idinformacion_Persona, numero_de_ticket))
        
        ticket_id = cursor.lastrowid

        query = '''
        MATCH (p:PERSONA { id: $user_id })
        CREATE (t:TICKET { numero_de_ticket: $numero_de_ticket })
        MERGE (p)-[:TIENE]->(t)
        RETURN p,t 
        '''
        neo4j_conn.execute_query(query, {
            "user_id": informacion_Persona_idinformacion_Persona,
            "numero_de_ticket": numero_de_ticket
        })

        # Insertar detalles del ticket en MySQL
        cursor.execute('''
            INSERT INTO detalles_ticket (ticket_idticket) 
            VALUES (%s)
        ''', (ticket_id,))

        connection.commit()
    except mysql.connector.Error as err:
        connection.rollback()
        return jsonify({"message": f"Error: {err}"}), 500
    finally:
        cursor.close()
        connection.close()

    return jsonify({"message": "Object and review added successfully"}), 201

# Obtener objetos
@app.route('/get_objects', methods=['GET'])
def get_objects():
    # Recuperar el email desde la sesión
    email = session.get('email')
    if not email:
        return jsonify({"message": "User not logged in"}), 401

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Obtener los objetos
    cursor.execute('SELECT o.idObjeto,o.Nombre, o.Descripcion, o.URL_Imagen FROM objeto o WHERE idObjeto NOT IN (SELECT b.objeto_idobjeto FROM banco b)')
    rows = cursor.fetchall()

            # Obtener los objetos que el usuario ha agregado, excluyendo los objetos en el banco
    cursor.execute('''
        SELECT o.idObjeto, o.Nombre, o.Descripcion, o.URL_Imagen 
        FROM objeto o
        INNER JOIN informacion_Persona ip ON o.informacion_Persona_idinformacion_Persona = ip.idinformacion_Persona
        WHERE ip.DireccionCorreo = %s
        AND o.idObjeto NOT IN (SELECT b.objeto_idobjeto FROM banco b)
    ''', (email,))
    rows2 = cursor.fetchall()

    # Obtener información del usuario
    cursor.execute('SELECT Nombre, DNI, DireccionCorreo, has_ticket FROM informacion_Persona WHERE DireccionCorreo = %s', (email,))
    info = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify({'objects': rows,'destino': rows2, 'info': info}), 200

#Obtener información de usuario
@app.route('/userinfo', methods=['GET'])
def get_user():
    email = session.get('email')
    if not email:
        return jsonify({"message": "User not logged in"}), 401
    
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Consulta optimizada con LEFT JOIN
    cursor.execute('''
        SELECT 
            iP.DNI,
            iP.DireccionCorreo,
            iP.FechaNacimiento,
            iP.Nombre,
            iP.password,
            dP.direccion,
            dP.departamento,
            dP.provincia,
            dP.distrito
        FROM 
            informacion_Persona iP
        LEFT JOIN 
            direccion_Persona dP 
        ON 
            iP.idinformacion_Persona = dP.informacion_Persona_idinformacion_Persona
        WHERE 
            iP.DireccionCorreo = %s
    ''', (email,))

    rows = cursor.fetchall()
    cursor.close()
    connection.close()
    return jsonify({'user': rows}), 200

#Eliminar usuario
@app.route('/delete_user', methods=['DELETE'])
def delete_user():
    email = session.get('email')  # Obtener el correo del usuario autenticado
    if not email:
        return jsonify({"message": "User not logged in"}), 401

    # Obtener el ID del usuario desde la base de datos relacional (MySQL)
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("SELECT idinformacion_Persona FROM informacion_Persona WHERE DireccionCorreo = %s", (email,))
    user = cursor.fetchone()

    if not user:
        return jsonify({"message": "User not found"}), 404

    user_id = user['idinformacion_Persona']

    try:
        # 1. Eliminar las relaciones y el nodo en Neo4j
        neo4j_conn.execute_query('''
            MATCH (n:PERSONA {id: $user_id})-[r]-(nodo_relacionado)
            DETACH DELETE n, nodo_relacionado
        ''', {"user_id": user_id})

        # 2. Eliminar los datos del usuario en MySQL
        cursor.execute("DELETE FROM reseñas_objetos WHERE objeto_idobjeto IN (SELECT idobjeto FROM objeto WHERE informacion_Persona_idinformacion_Persona = %s)", (user_id,))
        cursor.execute("DELETE FROM objeto WHERE informacion_Persona_idinformacion_Persona = %s", (user_id,))
        cursor.execute("DELETE FROM banco WHERE dejado_por = %s", (user_id,))
        cursor.execute("DELETE FROM direccion_Persona WHERE informacion_Persona_idinformacion_Persona = %s", (user_id,))
        cursor.execute("DELETE FROM informacion_Persona WHERE idinformacion_Persona = %s", (user_id,))

        connection.commit()

        return jsonify({"message": "User and associated data deleted successfully"}), 200

    except Exception as e:
        connection.rollback()
        print(f"Error deleting user: {e}")
        return jsonify({"message": f"Error deleting user: {str(e)}"}), 500

    finally:
        cursor.close()
        connection.close()


# Modificar usuario
@app.route('/modify_user', methods=['PATCH'])
def modify_user():
    email = session.get('email')  # Obtener el correo del usuario autenticado
    if not email:
        return jsonify({"message": "User not logged in"}), 401

    data = request.get_json()
    fields_to_update_persona = []
    values_persona = []
    fields_to_update_direccion = []
    values_direccion = []

    # Conexión a la base de datos
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Verificar que el usuario existe en la tabla `informacion_persona`
        cursor.execute("SELECT idinformacion_persona FROM informacion_Persona WHERE DireccionCorreo = %s", (email,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"message": "User not found"}), 404
        user_id = user[0]  # Obtener el ID del usuario (clave foránea en `direccion_persona`)

        # Actualización de `informacion_persona`
        neo4j_persona_updates = {}  # Para almacenar los datos que se enviarán a Neo4j
        if 'Nombre' in data:
            fields_to_update_persona.append('Nombre = %s')
            values_persona.append(data['Nombre'])
            neo4j_persona_updates['name'] = data['Nombre']
        if 'DNI' in data:
            fields_to_update_persona.append('DNI = %s')
            values_persona.append(data['DNI'])
            neo4j_persona_updates['dni'] = data['DNI']
        if 'DireccionCorreo' in data:
            fields_to_update_persona.append('DireccionCorreo = %s')
            values_persona.append(data['DireccionCorreo'])
            neo4j_persona_updates['correo'] = data['DireccionCorreo']
        if 'FechaNacimiento' in data:
            fields_to_update_persona.append('FechaNacimiento = %s')
            values_persona.append(data['FechaNacimiento'])
            neo4j_persona_updates['fechaNacimiento'] = data['FechaNacimiento']
        if 'password' in data and data['password']:
            fields_to_update_persona.append('password = %s')
            values_persona.append(data['password'])

        # Si hay campos para actualizar en `informacion_persona`
        if fields_to_update_persona:
            query_persona = f"UPDATE informacion_Persona SET {', '.join(fields_to_update_persona)} WHERE DireccionCorreo = %s"
            values_persona.append(email)
            cursor.execute(query_persona, values_persona)

            if 'DireccionCorreo' in data:
                session['email'] = data['DireccionCorreo']

        # Actualización de `direccion_persona`
        neo4j_direccion_updates = {}  # Para almacenar los datos que se enviarán a Neo4j
        if 'direccion' in data:
            fields_to_update_direccion.append('direccion = %s')
            values_direccion.append(data['direccion'])
            neo4j_direccion_updates['direccion'] = data['direccion']
        if 'departamento' in data:
            fields_to_update_direccion.append('departamento = %s')
            values_direccion.append(data['departamento'])
            neo4j_direccion_updates['departamento'] = data['departamento']
        if 'provincia' in data:
            fields_to_update_direccion.append('provincia = %s')
            values_direccion.append(data['provincia'])
            neo4j_direccion_updates['provincia'] = data['provincia']
        if 'distrito' in data:
            fields_to_update_direccion.append('distrito = %s')
            values_direccion.append(data['distrito'])
            neo4j_direccion_updates['distrito'] = data['distrito']

        # Si hay campos para actualizar en `direccion_persona`
        if fields_to_update_direccion:
            query_direccion = f"UPDATE direccion_Persona SET {', '.join(fields_to_update_direccion)} WHERE informacion_persona_idinformacion_persona = %s"
            values_direccion.append(user_id)
            cursor.execute(query_direccion, values_direccion)

        # Actualizar en Neo4j
        if neo4j_persona_updates:
            query_neo4j_persona = '''
            MATCH (p:PERSONA {correo: $correo_antiguo})
            SET p += $updates
            RETURN p
            '''
            neo4j_conn.execute_query(query_neo4j_persona, {
                "correo_antiguo": email,
                "updates": neo4j_persona_updates
            })

        if neo4j_direccion_updates:
            # Primero, encontrar la dirección actual y actualizarla.
            query_neo4j_direccion = '''
            MATCH (p:PERSONA {correo: $correo})
            MATCH (p)-[:VIVE_EN]->(d:DIRECCION)
            SET d += $updates
            RETURN d
            '''
            neo4j_conn.execute_query(query_neo4j_direccion, {
                "correo": email,
                "updates": neo4j_direccion_updates
            })

        # Confirmar cambios
        connection.commit()

    except Exception as e:
        print(f"Error al modificar usuario: {e}")
        connection.rollback()
        return jsonify({"message": "Internal server error"}), 500

    finally:
        cursor.close()
        connection.close()

    return jsonify({"message": "User updated successfully"}), 200


# Objetos en banco
@app.route('/bancoObjetos', methods=['GET'])
def get_banco_objetos():
    email = session.get('email')
    if not email:
        return jsonify({"message": "User not logged in"}), 401
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute('SELECT Nombre,idobjeto, Descripcion FROM objeto o JOIN banco b ON o.idobjeto=b.objeto_idobjeto WHERE fecha_de_salida IS NULL')
    rows = cursor.fetchall()

    cursor.execute('SELECT has_ticket FROM informacion_Persona WHERE DireccionCorreo = %s', (email,))
    info = cursor.fetchall()

    cursor.close()
    connection.close()
    return jsonify({'banco_objetos': rows,'info':info}), 200


@app.route('/usuarios', methods=['GET'])
def get_usuarios():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute('SELECT * FROM informacion_Persona')
    rows = cursor.fetchall()
    cursor.close()
    connection.close()
    return jsonify({'usuarios': rows}), 200

@app.route('/objeto', methods=['GET'])
def get_objeto():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute('SELECT * FROM objeto')
    rows = cursor.fetchall()
    cursor.close()
    connection.close()
    return jsonify({'objetos': rows}), 200

@app.route('/objetoPorId/<int:id>', methods=['GET'])
def get_objetoPorId(id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute('''
        SELECT o.Nombre, o.Descripcion, o.URL_Imagen, o.categoria, r.estado_estético, r.estado_funcional, r.estado_garantia 
        FROM objeto o 
        JOIN reseñas_objetos r ON r.objeto_idobjeto = o.idobjeto 
        WHERE o.idobjeto = %s
    ''', (id,))
    row = cursor.fetchone()
    cursor.close()
    connection.close()
    if row:
        return jsonify({'objeto': row}), 200
    else:
        return jsonify({"message": "Object not found"}), 404

@app.route('/bancoRetiro', methods=['POST'])
def banco_retiro():
    informacion_Persona_idinformacion_Persona = session.get('idinformacion_Persona')
    if not informacion_Persona_idinformacion_Persona:
        return jsonify({"message": "User not logged in"}), 401
    
    data = request.get_json()
    objeto_idobjeto = data.get('objeto_idobjeto')
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        # MySQL: Seleccionar el idticket
        cursor.execute('''
            SELECT idticket 
            FROM ticket t 
            JOIN detalles_ticket dt ON t.idticket = dt.ticket_idticket 
            WHERE informacion_persona_idinformacion_Persona = %s 
            AND redimiendo_ticket IS NULL 
            LIMIT 1
        ''', (informacion_Persona_idinformacion_Persona,))
        
        ticket = cursor.fetchone()
        
        if not ticket:
            return jsonify({"message": "No available ticket found"}), 404
        
        idticket = ticket['idticket']
        
        # MySQL: Actualizar redimiendo_ticket en la tabla detalles_ticket
        cursor.execute('''
            UPDATE detalles_ticket
            SET redimiendo_ticket = CURRENT_TIMESTAMP
            WHERE ticket_idticket = %s
        ''', (idticket,))
        
        # MySQL: Actualizar fecha_de_salida y llevado_por en banco
        cursor.execute('''
            UPDATE banco
            SET fecha_de_salida = CURRENT_TIMESTAMP, llevado_por = %s
            WHERE objeto_idobjeto = %s
        ''', (informacion_Persona_idinformacion_Persona, objeto_idobjeto))

        # MySQL: Actualizar has_ticket
        cursor.execute('''
            UPDATE informacion_Persona
            SET has_ticket = has_ticket - 1
            WHERE idinformacion_Persona = %s
        ''', (informacion_Persona_idinformacion_Persona,))
        
        banco_id_banca = cursor.lastrowid
        
        # Neo4j: Actualizar la información en el grafo
        query_neo4j = '''
        MATCH (p:PERSONA { user_id: $user_id })
        MATCH (o:OBJETO { id: $objeto_id })
        MATCH (b:BANCO { id_banco: $id_banco })-[r:TIENE]->(o)
        MATCH (p)-[z:TIENE]->(t:TICKET { numero_de_ticket: $numero_de_ticket })
        DELETE r
        DETACH DELETE t
        MERGE (p)-[:LLEVO]->(o)
        RETURN p, o
    '''
        # Ejecutar la consulta pasando los parámetros correctamente
        neo4j_conn.execute_query(query_neo4j, {
            "user_id": informacion_Persona_idinformacion_Persona,  # Asegúrate de que esto tenga el valor correcto
            "objeto_id": objeto_idobjeto,  # Este es el parámetro que falta según el error, asegúrate de que objeto_id tenga un valor
            "id_banco": banco_id_banca,  # Asegúrate de que esto tenga el valor correcto
            "numero_de_ticket": idticket  # Asegúrate de que esto tenga el valor correcto
        })

        # Confirmar cambios en MySQL
        connection.commit()

    except Exception as err:
        connection.rollback()  # Revertir cambios en MySQL si hay errores
        return jsonify({"message": f"Error: {err}"}), 500

    finally:
        cursor.close()
        connection.close()

    return jsonify({"message": "Ticket retrieved and updated successfully", "idticket": idticket}), 200

@app.route('/send_exchange_request', methods=['POST'])
def send_exchange_request():
    data = request.get_json()
    usuario_id = session.get('idinformacion_Persona')  # ID de la persona que solicita el intercambio
    objeto_solicitado_nombre = data.get('objeto_solicitado_id')  # Nombre del objeto solicitado
    objeto_ofrecido_nombre = data.get('objeto_ofrecido_id')  # Nombre del objeto ofrecido

    print(f"usuario_id: {usuario_id}")
    print(f"objeto_solicitado_nombre: {objeto_solicitado_nombre}")
    print(f"objeto_ofrecido_nombre: {objeto_ofrecido_nombre}")
    
    if not usuario_id or not objeto_solicitado_nombre or not objeto_ofrecido_nombre:
        return jsonify({"message": "Faltan datos en la solicitud"}), 400

    try:
        # Conectar a la base de datos
        connection = get_db_connection()
        cursor = connection.cursor()

        # Buscar el ID del objeto solicitado por su nombre
        cursor.execute('''
            SELECT idobjeto, informacion_Persona_idInformacion_Persona
            FROM objeto
            WHERE Nombre = %s
            LIMIT 1
        ''', (objeto_solicitado_nombre,))
        result_solicitado = cursor.fetchone()

        if not result_solicitado:
            return jsonify({"message": "Objeto solicitado no encontrado"}), 404

        objeto_solicitado_id = result_solicitado[0]
        propietario_objeto_solicitado_id = result_solicitado[1]  # ID de la persona propietaria del objeto solicitado
        print(f"objeto_solicitado_id: {objeto_solicitado_id}")
        print(f"propietario_objeto_solicitado_id: {propietario_objeto_solicitado_id}")

        # Buscar el ID del objeto ofrecido por su nombre
        cursor.execute('''
            SELECT idobjeto, informacion_Persona_idInformacion_Persona
            FROM objeto
            WHERE Nombre = %s
            LIMIT 1
        ''', (objeto_ofrecido_nombre,))
        result_ofrecido = cursor.fetchone()

        if not result_ofrecido:
            return jsonify({"message": "Objeto ofrecido no encontrado"}), 404

        objeto_ofrecido_id = result_ofrecido[0]
        propietario_objeto_ofrecido_id = result_ofrecido[1]  # ID de la persona propietaria del objeto ofrecido
        print(f"objeto_ofrecido_id: {objeto_ofrecido_id}")
        print(f"propietario_objeto_ofrecido_id: {propietario_objeto_ofrecido_id}")

        # Insertar la solicitud de intercambio en el inbox de la persona que ofrece el objeto
        cursor.execute('''
            INSERT INTO inbox_Persona (informacion_Persona_idinformacion_Persona, objeto_pedido, objeto_ofrecido, estado_solicitud, fecha_solicitud)
            VALUES (%s, %s, %s, 'pendiente', NOW())
        ''', (propietario_objeto_ofrecido_id, objeto_ofrecido_id,objeto_solicitado_id))

        connection.commit()
        return jsonify({"message": "Solicitud de intercambio enviada correctamente"}), 201
    except Exception as e:
        print(f"Error al enviar solicitud de intercambio: {e}")
        return jsonify({"message": "Error interno del servidor"}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
@app.route('/update_inbox_status', methods=['POST'])
def update_inbox_status():
    data = request.get_json()
    id_solicitud = data.get('id_solicitud')
    nuevo_estado = data.get('nuevo_estado')

    if not id_solicitud or not nuevo_estado:
        return jsonify({"message": "Faltan datos en la solicitud"}), 400

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # Actualizar el estado de la solicitud en inbox_Persona
        cursor.execute('''
            UPDATE inbox_Persona
            SET estado_solicitud = %s
            WHERE id_solicitud = %s
        ''', (nuevo_estado, id_solicitud))

        # Si el nuevo estado es "Aceptada", insertar en la tabla Intercambio
        if nuevo_estado.lower() == 'aceptada':
            # Obtener los detalles de la solicitud para insertar en Intercambio
            cursor.execute('''
                SELECT objeto_pedido, objeto_ofrecido
                FROM inbox_Persona
                WHERE id_solicitud = %s
            ''', (id_solicitud,))
            solicitud = cursor.fetchone()

            if solicitud:
                objeto_pedido = solicitud[0]
                objeto_ofrecido = solicitud[1]

                # Obtener el propietario del objeto solicitado
                cursor.execute('''
                    SELECT informacion_Persona_idinformacion_Persona
                    FROM objeto
                    WHERE idobjeto = %s
                ''', (objeto_pedido,))
                propietario_solicitado = cursor.fetchone()

                # Obtener el propietario del objeto ofrecido
                cursor.execute('''
                    SELECT informacion_Persona_idinformacion_Persona
                    FROM objeto
                    WHERE idobjeto = %s
                ''', (objeto_ofrecido,))
                propietario_ofrecido = cursor.fetchone()

                if propietario_solicitado and propietario_ofrecido:
                    persona_id_solicitado = propietario_solicitado[0]
                    persona_id_ofrecido = propietario_ofrecido[0]

                    # Insertar en la tabla Intercambio
                    cursor.execute('''
                        INSERT INTO Intercambio (objeto_idobjeto, objeto_idobjeto1, informacion_Persona_idinformacion_Persona, informacion_Persona_idinformacion_Persona1, Fecha)
                        VALUES (%s, %s, %s, %s, NOW())
                    ''', (objeto_pedido, objeto_ofrecido, persona_id_solicitado, persona_id_ofrecido))

        connection.commit()
        return jsonify({"message": "Estado actualizado correctamente"}), 200
    except Exception as e:
        print(f"Error al actualizar el estado: {e}")
        return jsonify({"message": "Error interno del servidor"}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

if __name__ == '__main__':
    app.run(debug=True)
