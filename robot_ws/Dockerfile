FROM ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-colcon-common-extensions \
    python3-rosdep \
    wget unzip \
    portaudio19-dev \
    libopencv-dev python3-opencv \
    ros-humble-slam-toolbox \
    ros-humble-navigation2 \
    ros-humble-nav2-bringup \
    ros-humble-twist-mux \
    ros-humble-pointcloud-to-laserscan \
    ros-humble-tf-transformations \
    ros-humble-rviz2 \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    vosk \
    lgpio \
    gpiod \
    sounddevice \
    adafruit-circuitpython-pca9685 \
    adafruit-blinka \
    depthai \
    onnxruntime

# Vosk PL model, downloaded once at build time
RUN mkdir -p /robot/model && \
    wget -q https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip -O /tmp/vosk-pl.zip && \
    unzip -q /tmp/vosk-pl.zip -d /tmp && \
    mv /tmp/vosk-model-small-pl-0.22/* /robot/model/ && \
    rm -rf /tmp/vosk-pl.zip /tmp/vosk-model-small-pl-0.22

WORKDIR /ros2_ws

COPY ros2_ws/src /ros2_ws/src

RUN . /opt/ros/humble/setup.sh && \
    rosdep init || true && rosdep update && \
    rosdep install --from-paths src --ignore-src -r -y

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc && \
    echo "test -f /ros2_ws/install/setup.bash && source /ros2_ws/install/setup.bash" >> /root/.bashrc

CMD ["bash"]
