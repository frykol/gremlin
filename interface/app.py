import tkinter as tk

class App:


    root = tk.Tk()
    root.title("Test")
    root.geometry("1600x800")
    b1 = tk.Button(root, text = 'b1', command = root.destroy)
    b1.place(relx = 0, rely = 0, relwidth=0.25, relheight=0.2)
    b2 = tk.Button(root, text = 'b2', command = root.destroy)
    b2.place(relx = 0, rely = 0.2, relwidth=0.25, relheight=0.2)
    b3 = tk.Button(root, text = 'b3', command = root.destroy)
    b3.place(relx = 0, rely = 0.4, relwidth=0.25, relheight=0.2)
    frame = tk.Frame(root, bg="lightblue", bd=3, relief=tk.RIDGE)
    frame.place(relx = 0.25, rely = 0, relheight = 0.6, relwidth = 0.5)
    test_width = root.winfo_width()
    test_height = root.winfo_height()
    def on_resize(event):
        print("Resize okna:", event.width, event.height)

    root.bind("<Configure>", on_resize)
    root.mainloop() 