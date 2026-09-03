import cv2
import os
import time

# CONFIG
ESP32_CAM_IP = '10.10.30.36:80'
KNOWN_FACES_DIR = 'known_faces'
SAMPLES_TO_CAPTURE = 30

def capture_faces(person_name, source=0):
    person_dir = os.path.join(KNOWN_FACES_DIR, person_name)
    if not os.path.exists(person_dir):
        os.makedirs(person_dir)
        
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    cap = cv2.VideoCapture(source)
    
    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return 0
        
    print(f"Starting capture for {person_name}...")
    print("Look at the camera and move your head slightly.")
    print("Press 'q' to stop early.")
    
    count = 0
    while count < SAMPLES_TO_CAPTURE:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break
            
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=8, minSize=(100,100))
        
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
            
            # Save only if one face is detected to ensure quality
            if len(faces) == 1:
                face_img = frame[y:y+h, x:x+w]
                img_path = os.path.join(person_dir, f"face_{count:03d}.jpg")
                cv2.imwrite(img_path, face_img)
                count += 1
                
                # Show flash effect
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                time.sleep(0.1) # Small delay between captures
                
        cv2.putText(frame, f"Capturing: {count}/{SAMPLES_TO_CAPTURE}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow('Face Registration', frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
    return count

def main():
    print("="*40)
    print("   Face Registration utility")
    print("="*40)
    
    while True:
        person_name = input("Enter name for this person (or 'q' to quit): ").strip()
        if person_name.lower() == 'q':
            break
            
        if not person_name:
            print("Name cannot be empty.")
            continue
            
        print("Select video source:")
        print("1. Web Camera (Local)")
        print(f"2. ESP32-CAM Stream ({ESP32_CAM_IP})")
        choice = input("Choice (1/2): ").strip()
        
        source = 0
        if choice == '2':
            source = f"http://{ESP32_CAM_IP}/stream"
            
        count = capture_faces(person_name, source)
        print(f"\nSuccessfully captured {count} images for {person_name}.")
        
        reg_another = input("Register another person? (y/n): ").strip().lower()
        if reg_another != 'y':
            break
            
    print("Done. You can now run main.py which will automatically train on the new data.")

if __name__ == '__main__':
    main()
